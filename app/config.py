import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(basedir, "school.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File uploads (student photos, documents, receipts)
    UPLOAD_FOLDER = os.path.join(basedir, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB


class ProductionConfig(Config):
    """Used on the live server. Flask reads config classes as plain
    attribute bags (it never instantiates them), so the SECRET_KEY safety
    check happens in create_app() instead of __init__ — see app/__init__.py."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True     # only send cookies over HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PREFERRED_URL_SCHEME = "https"
