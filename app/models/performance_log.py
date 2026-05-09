from datetime import datetime, timezone
from bson import ObjectId
from app.database import get_db

ALGORITHMS = ("KMP", "Boyer-Moore", "Rabin-Karp", "AUTO")


class PerformanceLogModel:
    collection = "performance_logs"

    @staticmethod
    def _col():
        return get_db()[PerformanceLogModel.collection]

    @staticmethod
    def create(
        algorithm: str,
        file_path: str,
        text_size_bytes: int,
        duration_ms: float,
        matches_count: int,
        user_id: str = "",
    ) -> dict:
        doc = {
            "algorithm": algorithm,
            "file_path": file_path,
            "text_size_bytes": text_size_bytes,
            "duration_ms": duration_ms,
            "matches_count": matches_count,
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc),
        }
        result = PerformanceLogModel._col().insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    @staticmethod
    def find_by_algorithm(algorithm: str, limit: int = 100) -> list[dict]:
        return list(
            PerformanceLogModel._col()
            .find({"algorithm": algorithm})
            .sort("created_at", -1)
            .limit(limit)
        )

    @staticmethod
    def find_all(skip: int = 0, limit: int = 100) -> list[dict]:
        return list(
            PerformanceLogModel._col()
            .find({})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )

    @staticmethod
    def serialize(log: dict) -> dict:
        log = dict(log)
        log["id"] = str(log.pop("_id", ""))
        if "created_at" in log:
            log["created_at"] = log["created_at"].isoformat()
        return log

    # ── Analytics aggregations ────────────────────────────────────────────────

    @staticmethod
    def get_algorithm_breakdown(user_id: str = "") -> list[dict]:
        """Per-algorithm avg timing and match stats, optionally scoped to one user."""
        match_stage = {"$match": {"user_id": user_id}} if user_id else {"$match": {}}
        results = list(PerformanceLogModel._col().aggregate([
            match_stage,
            {"$group": {
                "_id":                "$algorithm",
                "count":              {"$sum": 1},
                "avg_duration_ms":    {"$avg": "$duration_ms"},
                "avg_matches":        {"$avg": "$matches_count"},
                "avg_text_size_bytes": {"$avg": "$text_size_bytes"},
            }},
            {"$sort": {"count": -1}},
        ]))
        return [
            {
                "algorithm":           r["_id"],
                "count":               r["count"],
                "avg_duration_ms":     round(r["avg_duration_ms"]     or 0.0, 4),
                "avg_matches":         round(r["avg_matches"]          or 0.0, 2),
                "avg_text_size_bytes": round(r["avg_text_size_bytes"]  or 0.0, 0),
            }
            for r in results
        ]
