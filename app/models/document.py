from datetime import datetime, timezone
from bson import ObjectId
from app.database import get_db


class DocumentModel:
    collection = "documents"

    @staticmethod
    def _col():
        return get_db()[DocumentModel.collection]

    @staticmethod
    def create(file_name: str, file_path: str, size_bytes: int, uploaded_by: str) -> dict:
        doc = {
            "file_name": file_name,
            "file_path": file_path,
            "size_bytes": size_bytes,
            "uploaded_by": uploaded_by,
            "created_at": datetime.now(timezone.utc),
        }
        result = DocumentModel._col().insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    @staticmethod
    def find_by_id(doc_id: str) -> dict | None:
        try:
            return DocumentModel._col().find_one({"_id": ObjectId(doc_id)})
        except Exception:
            return None

    @staticmethod
    def find_all(skip: int = 0, limit: int = 50) -> list[dict]:
        return list(DocumentModel._col().find({}).skip(skip).limit(limit))

    @staticmethod
    def delete(doc_id: str) -> bool:
        result = DocumentModel._col().delete_one({"_id": ObjectId(doc_id)})
        return result.deleted_count > 0

    @staticmethod
    def serialize(doc: dict) -> dict:
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id", ""))
        if "created_at" in doc:
            doc["created_at"] = doc["created_at"].isoformat()
        return doc
