"""
Statistics blueprint — /api/stats

GET /me              personal search statistics (totals, algorithm breakdown)
GET /algorithms      per-algorithm performance breakdown for the current user
GET /trending        globally trending queries in a recent time window
GET /recommendations rule-based, personalised algorithm recommendations
"""

from __future__ import annotations

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.models.performance_log import PerformanceLogModel
from app.models.search_history import SearchHistoryModel
from app.utils.decorators import login_required
from app.utils.responses import error, success

stats_bp = Blueprint("stats", __name__, url_prefix="/api/stats")


# ── Personal stats ────────────────────────────────────────────────────────────

@stats_bp.get("/me")
@login_required
def my_stats():
    """Aggregate search statistics for the authenticated user."""
    user_id = get_jwt_identity()
    stats   = SearchHistoryModel.get_user_stats(user_id)
    return success(stats, "User statistics")


# ── Algorithm breakdown ───────────────────────────────────────────────────────

@stats_bp.get("/algorithms")
@login_required
def algorithm_breakdown():
    """
    Per-algorithm avg timing, match count, and text-size stats.
    scope=me  (default) — current user only
    scope=global        — all users (any authenticated user may request this)
    """
    scope   = request.args.get("scope", "me")
    user_id = get_jwt_identity() if scope == "me" else ""
    data    = PerformanceLogModel.get_algorithm_breakdown(user_id=user_id)
    return success(data, "Algorithm performance breakdown")


# ── Trending searches ─────────────────────────────────────────────────────────

@stats_bp.get("/trending")
@login_required
def trending():
    """Most frequent search queries across all users within a rolling window."""
    limit = min(int(request.args.get("limit", 10)), 50)
    days  = min(int(request.args.get("days",  7)),  90)
    data  = SearchHistoryModel.get_trending(limit=limit, days=days)
    return success(data, f"Top {limit} trending queries (last {days} days)")


# ── Personalised recommendations ──────────────────────────────────────────────

@stats_bp.get("/recommendations")
@login_required
def recommendations():
    """
    Generate rule-based, personalised recommendations for the current user
    based on their search history and algorithm performance logs.
    """
    user_id   = get_jwt_identity()
    stats     = SearchHistoryModel.get_user_stats(user_id)
    algo_data = PerformanceLogModel.get_algorithm_breakdown(user_id=user_id)
    recs      = _build_recommendations(stats, algo_data)
    return success(recs, "Recommendations generated")


# ── Recommendation engine (pure rule-based, no ML) ────────────────────────────

def _build_recommendations(stats: dict, algo_breakdown: list[dict]) -> dict:
    """
    Derives algorithm and query recommendations from aggregate statistics.

    Rules applied (in order):
      R1  No history yet          → generic onboarding tip
      R2  Heavy AUTO user         → confirm AUTO is optimal
      R3  Faster alternative      → suggest switching if >1.3× speedup
      R4  Large-file searches     → recommend Boyer-Moore / streaming
      R5  High match count        → suggest multi-pattern / Aho-Corasick
      R6  Slow avg response       → suggest parallel mode or narrower text
      R7  Single-algorithm rut    → encourage compare endpoint
    """
    total        = stats.get("total_searches", 0)
    most_used    = stats.get("most_used_algorithm")
    algorithms   = stats.get("algorithms", {})
    avg_duration = stats.get("avg_duration_ms") or 0.0
    tips: list[str]     = []
    insights: list[str] = []

    # R1 — not enough data yet
    if total == 0:
        return {
            "recommended_algorithm": "AUTO",
            "tips": ["Complete a few searches to unlock personalised recommendations."],
            "insights":          [],
            "confidence":        "none",
            "based_on_searches": 0,
        }

    # identify fastest / slowest algorithms with at least 2 data points
    trusted = [e for e in algo_breakdown if e["count"] >= 2]
    fastest_entry = min(trusted, key=lambda e: e["avg_duration_ms"], default=None)
    fastest_alg   = fastest_entry["algorithm"] if fastest_entry else None

    # R2 — heavy AUTO usage
    auto_pct = algorithms.get("AUTO", 0) / total
    if auto_pct >= 0.7:
        tips.append(
            "You rely on AUTO selection — that is optimal. "
            "The heuristic engine picks the best algorithm for every query automatically."
        )

    # R3 — faster alternative exists
    if fastest_alg and most_used and fastest_alg != most_used:
        used_entry = next(
            (e for e in algo_breakdown if e["algorithm"] == most_used), None
        )
        if used_entry and used_entry["avg_duration_ms"] > 0:
            speedup = used_entry["avg_duration_ms"] / max(fastest_entry["avg_duration_ms"], 0.001)
            if speedup >= 1.3:
                insights.append(
                    f"{fastest_alg} runs {speedup:.1f}x faster than your most-used "
                    f"{most_used} on your typical inputs."
                )

    # R4 — large files
    if any(e.get("avg_text_size_bytes", 0) > 1_000_000 for e in algo_breakdown):
        tips.append(
            "For files larger than 1 MB, Boyer-Moore delivers the best average-case "
            "throughput. AUTO will select it automatically for long ASCII patterns."
        )

    # R5 — high average match count
    if any(e["avg_matches"] > 200 for e in algo_breakdown):
        insights.append(
            "Your searches return many matches on average. "
            "Use POST /api/search/multi (Aho-Corasick) to batch several "
            "related patterns in a single pass."
        )

    # R6 — slow average response
    if avg_duration > 500:
        tips.append(
            "Your average search takes over 500 ms. "
            "Enable parallel mode or reduce the search scope to improve throughput."
        )

    # R7 — stuck on one algorithm
    unique_algos = sum(1 for v in algorithms.values() if v > 0)
    if unique_algos == 1 and total >= 5:
        tips.append(
            "You always use the same algorithm. "
            "Try POST /api/search/compare to benchmark all algorithms on your input "
            "and find the fastest one for your data."
        )

    recommended = fastest_alg or most_used or "AUTO"
    confidence  = "high" if total >= 20 else "medium" if total >= 5 else "low"

    return {
        "recommended_algorithm": recommended,
        "tips":                  tips,
        "insights":              insights,
        "confidence":            confidence,
        "based_on_searches":     total,
    }
