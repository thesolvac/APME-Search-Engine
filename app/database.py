from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from config import get_config

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is not None:
        return _db

    cfg = get_config()
    try:
        _client = MongoClient(cfg.MONGO_URI, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")
        db_name = cfg.MONGO_URI.rsplit("/", 1)[-1].split("?")[0]
        _db = _client[db_name]
        _create_indexes(_db)
        return _db
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        raise RuntimeError(f"MongoDB connection failed: {e}") from e


def _create_indexes(db):
    db.users.create_index([("email", ASCENDING)], unique=True)
    db.users.create_index([("username", ASCENDING)], unique=True)
    db.documents.create_index([("file_path", ASCENDING)])
    db.documents.create_index([("created_at", ASCENDING)])
    db.search_history.create_index([("user_id", ASCENDING)])
    db.search_history.create_index([("run_at", ASCENDING)])
    db.performance_logs.create_index([("algorithm", ASCENDING)])
    db.performance_logs.create_index([("created_at", ASCENDING)])
