import re
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from app.database import get_db


class SearchHistoryModel:
    collection = "search_history"

    @staticmethod
    def _col():
        return get_db()[SearchHistoryModel.collection]

    @staticmethod
    def create(
        user_id: str,
        query: str,
        algorithm: str,
        files: list[str],
        matches_count: int,
        duration_ms: float,
    ) -> dict:
        doc = {
            "user_id": user_id,
            "query": query,
            "algorithm": algorithm,
            "files": files,
            "matches_count": matches_count,
            "duration_ms": duration_ms,
            "run_at": datetime.now(timezone.utc),
        }
        result = SearchHistoryModel._col().insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    @staticmethod
    def find_by_user(user_id: str, skip: int = 0, limit: int = 50) -> list[dict]:
        return list(
            SearchHistoryModel._col()
            .find({"user_id": user_id})
            .sort("run_at", -1)
            .skip(skip)
            .limit(limit)
        )

    @staticmethod
    def find_all(skip: int = 0, limit: int = 50) -> list[dict]:
        return list(
            SearchHistoryModel._col()
            .find({})
            .sort("run_at", -1)
            .skip(skip)
            .limit(limit)
        )

    @staticmethod
    def serialize(record: dict) -> dict:
        record = dict(record)
        record["id"] = str(record.pop("_id", ""))
        if "run_at" in record:
            record["run_at"] = record["run_at"].isoformat()
        return record

    # ── Analytics aggregations ────────────────────────────────────────────────

    @staticmethod
    def get_user_stats(user_id: str) -> dict:
        """Return aggregate stats for a single user."""
        col = SearchHistoryModel._col()

        totals = list(col.aggregate([
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": None,
                "total_searches":  {"$sum": 1},
                "total_matches":   {"$sum": "$matches_count"},
                "avg_duration_ms": {"$avg": "$duration_ms"},
            }},
        ]))

        alg_counts = list(col.aggregate([
            {"$match": {"user_id": user_id}},
            {"$group": {"_id": "$algorithm", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]))

        stats: dict = {"total_searches": 0, "total_matches": 0, "avg_duration_ms": 0.0}
        if totals:
            row = totals[0]
            stats["total_searches"]  = row["total_searches"]
            stats["total_matches"]   = row["total_matches"]
            stats["avg_duration_ms"] = round(row["avg_duration_ms"] or 0.0, 4)

        alg_map = {r["_id"]: r["count"] for r in alg_counts}
        stats["algorithms"]           = alg_map
        stats["most_used_algorithm"]  = alg_counts[0]["_id"] if alg_counts else None
        return stats

    @staticmethod
    def get_trending(limit: int = 10, days: int = 7) -> list[dict]:
        """Return the most frequent queries across all users in the given window."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        results = list(SearchHistoryModel._col().aggregate([
            {"$match": {"run_at": {"$gte": since}}},
            {"$group": {
                "_id":       "$query",
                "count":     {"$sum": 1},
                "last_seen": {"$max": "$run_at"},
            }},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]))
        return [
            {
                "query":     r["_id"],
                "count":     r["count"],
                "last_seen": r["last_seen"].isoformat() if r.get("last_seen") else None,
            }
            for r in results
        ]

    @staticmethod
    def autocomplete(prefix: str, user_id: str = "", limit: int = 10) -> list[str]:
        """Return distinct queries that start with *prefix* (case-insensitive)."""
        flt: dict = {"query": {"$regex": f"^{re.escape(prefix)}", "$options": "i"}}
        if user_id:
            flt["user_id"] = user_id
        results = list(SearchHistoryModel._col().aggregate([
            {"$match": flt},
            {"$group": {"_id": "$query", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]))
        return [r["_id"] for r in results]
