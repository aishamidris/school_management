from flask import Flask

from app.config import Config
from app.extensions import db, migrate, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Import models so Flask-Migrate can detect all tables
    from app import models  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        return User.query.get(int(user_id))

    # Register blueprints
    from app.blueprints.auth.routes import auth_bp
    from app.blueprints.main.routes import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    return app
