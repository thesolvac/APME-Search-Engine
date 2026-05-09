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
