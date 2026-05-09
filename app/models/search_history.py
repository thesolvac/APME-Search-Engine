from datetime import datetime, timezone
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
