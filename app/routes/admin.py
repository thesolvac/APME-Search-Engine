from flask import Blueprint, request
from pymongo.errors import DuplicateKeyError

from app.models.user import UserModel
from app.models.search_history import SearchHistoryModel
from app.models.performance_log import PerformanceLogModel
from app.utils.validators import validate_email, validate_password, validate_username
from app.utils.responses import success, error
from app.utils.decorators import admin_required

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


# ── Users ──────────────────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@admin_required
def list_users():
    skip = int(request.args.get("skip", 0))
    limit = min(int(request.args.get("limit", 50)), 200)
    users = UserModel.find_all(skip=skip, limit=limit)
    return success({"users": [UserModel.serialize(u) for u in users]})


@admin_bp.route("/users", methods=["POST"])
@admin_required
def create_user():
    data = request.get_json(silent=True)
    if not data:
        return error("Request body must be JSON.")

    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "user").strip()

    ok, msg = validate_username(username)
    if not ok:
        return error(msg)

    if not validate_email(email):
        return error("Invalid email address.")

    ok, msg = validate_password(password)
    if not ok:
        return error(msg)

    try:
        user = UserModel.create(username, email, password, role)
    except DuplicateKeyError:
        return error("A user with that email or username already exists.", 409)
    except ValueError as e:
        return error(str(e))

    return success({"user": UserModel.serialize(user)}, "User created.", 201)


@admin_bp.route("/users/<user_id>", methods=["GET"])
@admin_required
def get_user(user_id: str):
    user = UserModel.find_by_id(user_id)
    if not user:
        return error("User not found.", 404)
    return success({"user": UserModel.serialize(user)})


@admin_bp.route("/users/<user_id>", methods=["PUT"])
@admin_required
def update_user(user_id: str):
    data = request.get_json(silent=True)
    if not data:
        return error("Request body must be JSON.")

    allowed_fields = {"username", "email", "role", "is_active"}
    fields = {k: v for k, v in data.items() if k in allowed_fields}

    if not fields:
        return error("No valid fields provided for update.")

    if "username" in fields:
        ok, msg = validate_username(fields["username"])
        if not ok:
            return error(msg)

    if "email" in fields and not validate_email(fields["email"]):
        return error("Invalid email address.")

    try:
        updated = UserModel.update(user_id, fields)
    except ValueError as e:
        return error(str(e))
    except DuplicateKeyError:
        return error("Email or username already in use.", 409)

    if not updated:
        return error("User not found or no changes made.", 404)

    user = UserModel.find_by_id(user_id)
    return success({"user": UserModel.serialize(user)}, "User updated.")


@admin_bp.route("/users/<user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id: str):
    from flask_jwt_extended import get_jwt_identity
    if user_id == get_jwt_identity():
        return error("You cannot delete your own account.", 400)

    deleted = UserModel.delete(user_id)
    if not deleted:
        return error("User not found.", 404)
    return success(message="User deleted.")


# ── Stats / Logs ───────────────────────────────────────────────────────────────

@admin_bp.route("/search-history", methods=["GET"])
@admin_required
def all_search_history():
    skip = int(request.args.get("skip", 0))
    limit = min(int(request.args.get("limit", 50)), 200)
    records = SearchHistoryModel.find_all(skip=skip, limit=limit)
    return success({"records": [SearchHistoryModel.serialize(r) for r in records]})


@admin_bp.route("/performance-logs", methods=["GET"])
@admin_required
def all_performance_logs():
    skip = int(request.args.get("skip", 0))
    limit = min(int(request.args.get("limit", 100)), 500)
    algorithm = request.args.get("algorithm")

    if algorithm:
        logs = PerformanceLogModel.find_by_algorithm(algorithm, limit=limit)
    else:
        logs = PerformanceLogModel.find_all(skip=skip, limit=limit)

    return success({"logs": [PerformanceLogModel.serialize(l) for l in logs]})
