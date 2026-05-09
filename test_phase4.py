"""
Phase 4 smoke-tests — no live MongoDB required.

Tests are grouped into:
  1. Model aggregation helpers (offline, monkey-patched)
  2. Flask route integration via test client (DB disabled)
  3. Comparative algorithm analysis
  4. Recommendation engine logic
"""

from __future__ import annotations

import io
import os
import sys
import json
import types
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(__file__))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

_results: list[bool] = []


def chk(label: str, condition: bool) -> bool:
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_flask_app():
    """
    Create a Flask test app with DB disabled so no MongoDB is needed.
    We patch get_db() to raise immediately and set enable_db=False on the engine.
    """
    # Patch MongoDB before importing app so create_app() doesn't fail
    import app.database as _db_mod
    _db_mod.get_db = mock.MagicMock(side_effect=RuntimeError("no DB in test"))

    # Patch the engine singleton so it's DB-free
    import app.search_engine as _se
    _se._engine = None   # reset singleton

    def _patched_get_engine(**kwargs):
        kwargs["enable_db"] = False
        if _se._engine is None:
            _se._engine = _se.APMESearchEngine(**kwargs)
        return _se._engine

    _se.get_engine = _patched_get_engine

    # Patch DocumentModel.create so it doesn't hit DB
    import app.models.document as _doc_mod
    _doc_mod.DocumentModel.create = mock.MagicMock(return_value={"_id": "mock"})

    # Patch SearchHistoryModel analytics methods
    import app.models.search_history as _sh_mod
    _sh_mod.SearchHistoryModel.autocomplete = mock.MagicMock(return_value=["cat", "catch"])
    _sh_mod.SearchHistoryModel.get_user_stats = mock.MagicMock(return_value={
        "total_searches": 10,
        "total_matches": 42,
        "avg_duration_ms": 3.5,
        "algorithms": {"Boyer-Moore": 6, "KMP": 4},
        "most_used_algorithm": "Boyer-Moore",
    })
    _sh_mod.SearchHistoryModel.get_trending = mock.MagicMock(return_value=[
        {"query": "error", "count": 15, "last_seen": "2024-05-01T00:00:00+00:00"},
        {"query": "warning", "count": 8, "last_seen": "2024-05-02T00:00:00+00:00"},
    ])

    # Patch PerformanceLogModel analytics methods
    import app.models.performance_log as _pl_mod
    _pl_mod.PerformanceLogModel.get_algorithm_breakdown = mock.MagicMock(return_value=[
        {"algorithm": "Boyer-Moore", "count": 6,  "avg_duration_ms": 2.1,
         "avg_matches": 3.5, "avg_text_size_bytes": 500_000},
        {"algorithm": "KMP",         "count": 4,  "avg_duration_ms": 4.8,
         "avg_matches": 2.0, "avg_text_size_bytes": 200_000},
    ])

    from app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True

    # Patch the decorator's locally-bound names (from X import Y binds Y in the module namespace)
    import app.utils.decorators as _dec
    _dec.verify_jwt_in_request = mock.MagicMock(return_value=None)
    _dec.get_jwt_identity       = mock.MagicMock(return_value="testuser")
    _dec.UserModel.find_by_id   = mock.MagicMock(return_value={
        "_id": "testuser", "role": "user", "is_active": True,
    })

    # Patch each route module's locally-bound get_jwt_identity
    import app.routes.search as _rs
    _rs.get_jwt_identity = mock.MagicMock(return_value="testuser")

    import app.routes.stats as _rst
    _rst.get_jwt_identity = mock.MagicMock(return_value="testuser")

    return flask_app


# ─────────────────────────────────────────────────────────────────────────────
# 1. Model aggregation helpers (unit-level, offline)
# ─────────────────────────────────────────────────────────────────────────────

def test_model_aggregations():
    print("\n=== 1. Model Aggregation Helpers ===")
    ok = True

    # SearchHistoryModel.get_user_stats
    import app.models.search_history as sh
    stats = sh.SearchHistoryModel.get_user_stats("testuser")
    ok &= chk("get_user_stats returns total_searches", "total_searches" in stats)
    ok &= chk("get_user_stats returns algorithms dict", isinstance(stats.get("algorithms"), dict))
    ok &= chk("get_user_stats returns most_used_algorithm", "most_used_algorithm" in stats)

    # SearchHistoryModel.get_trending
    trending = sh.SearchHistoryModel.get_trending(limit=5, days=7)
    ok &= chk("get_trending returns a list", isinstance(trending, list))

    # SearchHistoryModel.autocomplete
    suggestions = sh.SearchHistoryModel.autocomplete("ca", user_id="testuser", limit=5)
    ok &= chk("autocomplete returns a list", isinstance(suggestions, list))

    # PerformanceLogModel.get_algorithm_breakdown
    import app.models.performance_log as pl
    breakdown = pl.PerformanceLogModel.get_algorithm_breakdown(user_id="testuser")
    ok &= chk("get_algorithm_breakdown returns a list", isinstance(breakdown, list))
    if breakdown:
        ok &= chk("breakdown entry has 'algorithm' key", "algorithm" in breakdown[0])
        ok &= chk("breakdown entry has 'avg_duration_ms'", "avg_duration_ms" in breakdown[0])

    _results.append(ok)
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# 2. Flask route integration
# ─────────────────────────────────────────────────────────────────────────────

def test_flask_routes():
    print("\n=== 2. Flask Route Integration ===")
    flask_app = _make_flask_app()
    ok = True

    with flask_app.test_client() as client:
        # Helper to add a fake JWT header (decorator is mocked, header value irrelevant)
        headers = {"Authorization": "Bearer fake.jwt.token"}

        # POST /api/search/text
        resp = client.post(
            "/api/search/text",
            json={"text": "the cat sat on the mat", "pattern": "cat"},
            headers=headers,
        )
        data = resp.get_json()
        ok &= chk("POST /api/search/text  status 200", resp.status_code == 200)
        ok &= chk("POST /api/search/text  match_count == 1",
                  data.get("data", {}).get("match_count") == 1)

        # POST /api/search/text missing pattern
        resp2 = client.post(
            "/api/search/text",
            json={"text": "hello"},
            headers=headers,
        )
        ok &= chk("POST /api/search/text  missing pattern -> 400", resp2.status_code == 400)

        # POST /api/search/file
        file_content = b"ERROR: disk full\nWARNING: low memory\nERROR: timeout\n"
        resp3 = client.post(
            "/api/search/file",
            data={
                "file":      (io.BytesIO(file_content), "test.log"),
                "pattern":   "ERROR",
                "algorithm": "KMP",
            },
            content_type="multipart/form-data",
            headers=headers,
        )
        d3 = resp3.get_json()
        ok &= chk("POST /api/search/file  status 200", resp3.status_code == 200)
        ok &= chk("POST /api/search/file  match_count == 2",
                  d3.get("data", {}).get("match_count") == 2)
        ok &= chk("POST /api/search/file  file_name present",
                  d3.get("data", {}).get("file_name") == "test.log")

        # POST /api/search/file bad extension
        resp4 = client.post(
            "/api/search/file",
            data={
                "file":    (io.BytesIO(b"binary"), "photo.exe"),
                "pattern": "x",
            },
            content_type="multipart/form-data",
            headers=headers,
        )
        ok &= chk("POST /api/search/file  disallowed extension -> 400", resp4.status_code == 400)

        # POST /api/search/multi
        resp5 = client.post(
            "/api/search/multi",
            json={"text": "the cat sat on the mat with a rat",
                  "patterns": ["cat", "rat", "mat"]},
            headers=headers,
        )
        d5 = resp5.get_json()
        ok &= chk("POST /api/search/multi  status 200", resp5.status_code == 200)
        ok &= chk("POST /api/search/multi  'results' key present",
                  "results" in d5.get("data", {}))
        ok &= chk("POST /api/search/multi  cat found",
                  d5["data"]["results"].get("cat", {}).get("match_count", 0) >= 1)

        # POST /api/search/compare
        resp6 = client.post(
            "/api/search/compare",
            json={"text": "the quick brown fox jumps over the lazy dog " * 500,
                  "pattern": "fox"},
            headers=headers,
        )
        d6 = resp6.get_json()
        ok &= chk("POST /api/search/compare  status 200", resp6.status_code == 200)
        ok &= chk("POST /api/search/compare  all 4 algorithms present",
                  len(d6.get("data", {}).get("comparison", {})) == 4)
        ok &= chk("POST /api/search/compare  fastest field set",
                  bool(d6.get("data", {}).get("fastest")))
        ok &= chk("POST /api/search/compare  auto_selected field set",
                  bool(d6.get("data", {}).get("auto_selected")))

        # GET /api/search/autocomplete
        resp7 = client.get(
            "/api/search/autocomplete?q=ca&scope=global",
            headers=headers,
        )
        d7 = resp7.get_json()
        ok &= chk("GET /api/search/autocomplete  status 200", resp7.status_code == 200)
        ok &= chk("GET /api/search/autocomplete  returns list",
                  isinstance(d7.get("data"), list))

        # GET /api/stats/me
        resp8 = client.get("/api/stats/me", headers=headers)
        d8 = resp8.get_json()
        ok &= chk("GET /api/stats/me  status 200", resp8.status_code == 200)
        ok &= chk("GET /api/stats/me  total_searches present",
                  "total_searches" in d8.get("data", {}))

        # GET /api/stats/algorithms
        resp9 = client.get("/api/stats/algorithms", headers=headers)
        ok &= chk("GET /api/stats/algorithms  status 200", resp9.status_code == 200)

        # GET /api/stats/trending
        resp10 = client.get("/api/stats/trending?limit=5&days=7", headers=headers)
        d10 = resp10.get_json()
        ok &= chk("GET /api/stats/trending  status 200", resp10.status_code == 200)
        ok &= chk("GET /api/stats/trending  returns list",
                  isinstance(d10.get("data"), list))

        # GET /api/stats/recommendations
        resp11 = client.get("/api/stats/recommendations", headers=headers)
        d11 = resp11.get_json()
        ok &= chk("GET /api/stats/recommendations  status 200", resp11.status_code == 200)
        ok &= chk("GET /api/stats/recommendations  recommended_algorithm present",
                  "recommended_algorithm" in d11.get("data", {}))
        ok &= chk("GET /api/stats/recommendations  tips is list",
                  isinstance(d11.get("data", {}).get("tips"), list))
        ok &= chk("GET /api/stats/recommendations  confidence present",
                  "confidence" in d11.get("data", {}))

    _results.append(ok)
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# 3. Comparative analysis (direct, no Flask)
# ─────────────────────────────────────────────────────────────────────────────

def test_compare_direct():
    print("\n=== 3. Comparative Analysis (direct) ===")
    import concurrent.futures
    from app.engine import wrapper as _w
    from app.processing.heuristics import select_algorithm

    text    = (b"the quick brown fox jumps over the lazy dog. ") * 10_000
    pattern = b"fox"

    alg_fns = {
        "KMP":         _w.search_kmp,
        "Boyer-Moore": _w.search_boyer_moore,
        "Rabin-Karp":  _w.search_rabin_karp,
        "Shift-Or":    _w.search_shift_or,
    }

    comparison: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fn, text, pattern): name for name, fn in alg_fns.items()}
        for fut in concurrent.futures.as_completed(futs):
            name = futs[fut]
            sr   = fut.result()
            comparison[name] = {"duration_ms": sr.duration_ms, "match_count": len(sr.matches)}

    auto = select_algorithm(pattern, text_sample=text[:65_536], text_len=len(text))

    ok = True
    ok &= chk("all 4 algorithms ran", len(comparison) == 4)
    ok &= chk("all found same match count",
              len({v["match_count"] for v in comparison.values()}) == 1)
    ok &= chk("match count == 10000",
              list(comparison.values())[0]["match_count"] == 10_000)
    ok &= chk("AUTO selection returned", bool(auto))

    for name, stats in comparison.items():
        print(f"    {name:15s}  {stats['duration_ms']:.2f} ms  "
              f"{stats['match_count']} matches"
              + ("  <- AUTO" if name == auto else ""))

    _results.append(ok)
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# 4. Recommendation engine logic
# ─────────────────────────────────────────────────────────────────────────────

def test_recommendations_logic():
    print("\n=== 4. Recommendation Engine Logic ===")
    from app.routes.stats import _build_recommendations
    ok = True

    # Case A: no history
    recs_a = _build_recommendations(
        {"total_searches": 0, "most_used_algorithm": None, "algorithms": {},
         "avg_duration_ms": 0},
        [],
    )
    ok &= chk("no-history -> confidence 'none'", recs_a["confidence"] == "none")
    ok &= chk("no-history -> AUTO recommended", recs_a["recommended_algorithm"] == "AUTO")

    # Case B: heavy AUTO user
    recs_b = _build_recommendations(
        {"total_searches": 10, "most_used_algorithm": "AUTO",
         "algorithms": {"AUTO": 8, "KMP": 2}, "avg_duration_ms": 5.0},
        [{"algorithm": "AUTO", "count": 8, "avg_duration_ms": 3.0,
          "avg_matches": 10, "avg_text_size_bytes": 500}],
    )
    ok &= chk("heavy-AUTO -> tip about AUTO", any("AUTO" in t for t in recs_b["tips"]))

    # Case C: faster alternative available
    recs_c = _build_recommendations(
        {"total_searches": 20, "most_used_algorithm": "KMP",
         "algorithms": {"KMP": 16, "Boyer-Moore": 4}, "avg_duration_ms": 12.0},
        [
            {"algorithm": "KMP",         "count": 16, "avg_duration_ms": 10.0,
             "avg_matches": 5, "avg_text_size_bytes": 200_000},
            {"algorithm": "Boyer-Moore", "count": 4,  "avg_duration_ms": 3.0,
             "avg_matches": 5, "avg_text_size_bytes": 200_000},
        ],
    )
    ok &= chk("faster-alt -> insight mentioning Boyer-Moore",
              any("Boyer-Moore" in ins for ins in recs_c["insights"]))
    ok &= chk("faster-alt -> recommended_algorithm is Boyer-Moore",
              recs_c["recommended_algorithm"] == "Boyer-Moore")
    ok &= chk("confidence high (>=20 searches)", recs_c["confidence"] == "high")

    # Case D: slow avg duration triggers tip
    recs_d = _build_recommendations(
        {"total_searches": 5, "most_used_algorithm": "Rabin-Karp",
         "algorithms": {"Rabin-Karp": 5}, "avg_duration_ms": 800.0},
        [{"algorithm": "Rabin-Karp", "count": 5, "avg_duration_ms": 800.0,
          "avg_matches": 3, "avg_text_size_bytes": 100}],
    )
    ok &= chk("slow-avg -> tip about 500ms threshold",
              any("500" in t for t in recs_d["tips"]))

    _results.append(ok)
    return ok


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_model_aggregations()
    test_compare_direct()
    test_recommendations_logic()
    test_flask_routes()     # run last (patches globals)

    print("\n" + "=" * 50)
    if all(_results):
        print("ALL PHASE 4 TESTS PASSED")
        sys.exit(0)
    else:
        print(f"FAILURES: {_results.count(False)} / {len(_results)} suites")
        sys.exit(1)
