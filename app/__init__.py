from flask import Flask
from flask_jwt_extended import JWTManager
from datetime import timedelta

from config import get_config


def create_app() -> Flask:
    cfg = get_config()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(cfg)
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(seconds=cfg.JWT_ACCESS_TOKEN_EXPIRES)

    # Extensions
    JWTManager(app)

    # Ensure DB connection is tested at startup
    with app.app_context():
        from app.database import get_db
        try:
            get_db()
        except RuntimeError as e:
            app.logger.error(str(e))

    # Blueprints
    from app.routes.auth   import auth_bp
    from app.routes.admin  import admin_bp
    from app.routes.search import search_bp
    from app.routes.stats  import stats_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(stats_bp)

    # Root health-check
    @app.route("/api/health")
    def health():
        return {"status": "ok", "service": "APME Search Engine"}, 200

    return app
