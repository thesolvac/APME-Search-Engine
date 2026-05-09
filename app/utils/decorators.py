from functools import wraps
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from app.models.user import UserModel
from app.utils.responses import error


def admin_required(fn):
    """Decorator: requires a valid JWT and admin role."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return error("Missing or invalid token.", 401)

        user_id = get_jwt_identity()
        user = UserModel.find_by_id(user_id)

        if not user:
            return error("User not found.", 401)
        if user.get("role") != "admin":
            return error("Admin access required.", 403)
        if not user.get("is_active", True):
            return error("Account is disabled.", 403)

        return fn(*args, **kwargs)

    return wrapper


def login_required(fn):
    """Decorator: requires a valid JWT (any role)."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return error("Missing or invalid token.", 401)

        user_id = get_jwt_identity()
        user = UserModel.find_by_id(user_id)

        if not user:
            return error("User not found.", 401)
        if not user.get("is_active", True):
            return error("Account is disabled.", 403)

        return fn(*args, **kwargs)

    return wrapper
