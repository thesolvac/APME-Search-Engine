from flask import Blueprint, request
from flask_jwt_extended import create_access_token, get_jwt_identity
from pymongo.errors import DuplicateKeyError

from app.models.user import UserModel
from app.utils.validators import validate_email, validate_password, validate_username
from app.utils.responses import success, error
from app.utils.decorators import login_required

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)
    if not data:
        return error("Request body must be JSON.")

    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "user").strip()

    # Validate fields
    ok, msg = validate_username(username)
    if not ok:
        return error(msg)

    if not validate_email(email):
        return error("Invalid email address.")

    ok, msg = validate_password(password)
    if not ok:
        return error(msg)

    # Only allow admin creation if the requester is an admin (optional field)
    if role == "admin":
        return error(
            "Cannot self-register as admin. Contact an administrator.", 403
        )

    try:
        user = UserModel.create(username, email, password, role)
    except DuplicateKeyError:
        return error("A user with that email or username already exists.", 409)
    except ValueError as e:
        return error(str(e))

    token = create_access_token(identity=str(user["_id"]))
    return success(
        {"user": UserModel.serialize(user), "access_token": token},
        "Registration successful.",
        201,
    )


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)
    if not data:
        return error("Request body must be JSON.")

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return error("Email and password are required.")

    user = UserModel.find_by_email(email)
    if not user or not UserModel.check_password(password, user["password_hash"]):
        return error("Invalid email or password.", 401)

    if not user.get("is_active", True):
        return error("This account has been disabled.", 403)

    token = create_access_token(identity=str(user["_id"]))
    return success(
        {"user": UserModel.serialize(user), "access_token": token},
        "Login successful.",
    )


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    user_id = get_jwt_identity()
    user = UserModel.find_by_id(user_id)
    if not user:
        return error("User not found.", 404)
    return success({"user": UserModel.serialize(user)})


@auth_bp.route("/change-password", methods=["PUT"])
@login_required
def change_password():
    data = request.get_json(silent=True)
    if not data:
        return error("Request body must be JSON.")

    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    user_id = get_jwt_identity()
    user = UserModel.find_by_id(user_id)

    if not UserModel.check_password(current_password, user["password_hash"]):
        return error("Current password is incorrect.", 401)

    ok, msg = validate_password(new_password)
    if not ok:
        return error(msg)

    new_hash = UserModel.hash_password(new_password)
    UserModel.update(user_id, {"password_hash": new_hash})
    return success(message="Password updated successfully.")
