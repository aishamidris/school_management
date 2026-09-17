from flask import Flask

from app.config import Config, ProductionConfig
from app.extensions import db, migrate, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Refuse to boot in production with the default SECRET_KEY — this
    # class attribute is public in this codebase, so shipping with it
    # means anyone can forge session cookies. Checked here (after Flask
    # has actually loaded the config values) rather than on the config
    # class itself, since Flask reads config classes as plain attribute
    # bags and never instantiates them.
    if config_class is ProductionConfig and app.config["SECRET_KEY"] == "dev-secret-key-change-me":
        raise RuntimeError(
            "Refusing to start: SECRET_KEY is still the default. Generate a real one with "
            '`python -c "import secrets; print(secrets.token_hex(32))"` '
            "and set it in your production .env file."
        )

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
    from app.blueprints.students.routes import students_bp
    from app.blueprints.finance.routes import finance_bp
    from app.blueprints.results.routes import results_bp
    from app.blueprints.staff.routes import staff_bp
    from app.blueprints.reconciliation.routes import reconciliation_bp
    from app.blueprints.exams.routes import exams_bp
    from app.blueprints.permissions.routes import permissions_bp
    from app.blueprints.attendance.routes import attendance_bp
    from app.blueprints.audit.routes import audit_bp
    from app.blueprints.profile.routes import profile_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(results_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(reconciliation_bp)
    app.register_blueprint(exams_bp)
    app.register_blueprint(permissions_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(profile_bp)

    # Make has_perm('key') available in every template, checking the
    # currently logged-in user against the granular permission system.
    from app.utils.permissions import has_permission
    from flask_login import current_user

    @app.context_processor
    def inject_permission_helper():
        return {"has_perm": lambda key: has_permission(current_user, key)}

    # Auto-seed on boot — for free-tier hosts (Render's free plan, for
    # example) that don't allow shell access or one-off commands, this is
    # the only way to get data into a fresh database. Controlled by
    # environment variables so it's opt-in and never runs unexpectedly on
    # a real production server:
    #   AUTO_SEED=true        -> creates owner/classes/grading/permissions
    #   AUTO_SEED_DEMO=true   -> also loads a full realistic demo dataset
    # Both are idempotent (safe to run on every single boot).
    import os
    if os.environ.get("AUTO_SEED", "").lower() == "true":
        with app.app_context():
            from app.seeding.base_seed import seed_base_data
            seed_base_data()
            if os.environ.get("AUTO_SEED_DEMO", "").lower() == "true":
                from app.seeding.demo_seed import seed_demo_data
                seed_demo_data()

    return app
