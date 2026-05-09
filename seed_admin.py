"""
Run once to create the initial admin account:
    python seed_admin.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

from app.database import get_db  # noqa: E402 — must be after load_dotenv
from app.models.user import UserModel
from pymongo.errors import DuplicateKeyError

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@apme.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin1234!")


def seed():
    try:
        get_db()
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return

    try:
        user = UserModel.create(ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD, role="admin")
        print(f"[OK] Admin created: {ADMIN_EMAIL}  id={user['_id']}")
    except DuplicateKeyError:
        print(f"[SKIP] Admin '{ADMIN_EMAIL}' already exists.")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    seed()
