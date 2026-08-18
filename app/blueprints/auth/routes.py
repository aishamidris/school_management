from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models.user import User
from app.utils.audit import log_action

auth_bp = Blueprint("auth", __name__, template_folder="../../templates/auth")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()  # email or phone
        password = request.form.get("password", "")

        user = User.query.filter(
            (User.email == identifier) | (User.phone == identifier)
        ).first()

        if user and user.is_locked():
            flash("This account is temporarily locked due to failed login attempts. Try again later.", "danger")
            return render_template("auth/login.html")

        if user and user.check_password(password) and user.is_active:
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = datetime.utcnow()
            db.session.commit()

            login_user(user)
            log_action("auth.login", "User", user.id, description=f"{user.full_name} logged in")
            db.session.commit()
            return redirect(url_for("main.dashboard"))

        # Failed attempt
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                flash("Too many failed attempts. Account locked for 15 minutes.", "danger")
            db.session.commit()

        flash("Invalid credentials.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    log_action("auth.logout", "User", current_user.id, description=f"{current_user.full_name} logged out")
    db.session.commit()
    logout_user()
    return redirect(url_for("auth.login"))
