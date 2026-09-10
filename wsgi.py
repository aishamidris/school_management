"""Production entry point. Gunicorn imports this file and runs the `app`
object directly — it never calls app.run(), so Flask's development
server (and its debug mode) is never used in production.

Usage on the server:
    gunicorn --workers 3 --bind unix:school.sock wsgi:app
"""
from app import create_app
from app.config import ProductionConfig

app = create_app(ProductionConfig)
