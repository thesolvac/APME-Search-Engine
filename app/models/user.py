from datetime import datetime, timezone
from bson import ObjectId
import bcrypt
from app.database import get_db

ROLES = ("user", "admin")


class UserModel:
    collection = "users"

    @staticmethod
    def _col():
        return get_db()[UserModel.collection]

    @staticmethod
    def hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def check_password(plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode(), hashed.encode())

    @staticmethod
    def create(username: str, email: str, password: str, role: str = "user") -> dict:
        if role not in ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of {ROLES}.")

        doc = {
            "username": username.strip(),
            "email": email.strip().lower(),
            "password_hash": UserModel.hash_password(password),
            "role": role,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        result = UserModel._col().insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    @staticmethod
    def find_by_email(email: str) -> dict | None:
        return UserModel._col().find_one({"email": email.strip().lower()})

    @staticmethod
    def find_by_id(user_id: str) -> dict | None:
        try:
            return UserModel._col().find_one({"_id": ObjectId(user_id)})
        except Exception:
            return None

    @staticmethod
    def find_all(skip: int = 0, limit: int = 50) -> list[dict]:
        cursor = UserModel._col().find(
            {}, {"password_hash": 0}
        ).skip(skip).limit(limit)
        return list(cursor)

    @staticmethod
    def update(user_id: str, fields: dict) -> bool:
        allowed = {"username", "email", "role", "is_active", "password_hash"}
        update_data = {k: v for k, v in fields.items() if k in allowed}

        if not update_data:
            return False

        if "role" in update_data and update_data["role"] not in ROLES:
            raise ValueError(f"Invalid role. Must be one of {ROLES}.")

        if "email" in update_data:
            update_data["email"] = update_data["email"].strip().lower()

        update_data["updated_at"] = datetime.now(timezone.utc)

        result = UserModel._col().update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data},
        )
        return result.modified_count > 0

    @staticmethod
    def delete(user_id: str) -> bool:
        result = UserModel._col().delete_one({"_id": ObjectId(user_id)})
        return result.deleted_count > 0

    @staticmethod
    def serialize(user: dict) -> dict:
        user = dict(user)
        user.pop("password_hash", None)
        user["id"] = str(user.pop("_id", ""))
        if "created_at" in user:
            user["created_at"] = user["created_at"].isoformat()
        if "updated_at" in user:
            user["updated_at"] = user["updated_at"].isoformat()
        return user
