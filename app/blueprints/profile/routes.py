import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, current_app
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role, User
from app.models.academic import AcademicSession, Term
from app.models.exam import Result
from app.utils.audit import log_action
from app.utils.uploads import save_profile_photo
from app.utils.result_pdf import build_result_pdf

profile_bp = Blueprint("profile", __name__, template_folder="../../templates/profile")


def _current_term():
    session = AcademicSession.query.filter_by(is_current=True).first()
    if not session:
        return None
    return Term.query.filter_by(session_id=session.id, is_current=True).first()


def _profile_record():
    """The role-specific profile row (Staff or Student) for the logged-in
    user, or None for roles that don't have one (e.g. parent)."""
    if current_user.role in Role.STAFF_ROLES:
        return current_user.staff_profile
    if current_user.role == Role.STUDENT:
        return current_user.student_profile
    return None


@profile_bp.route("/profile")
@login_required
def view_profile():
    record = _profile_record()

    context = {"record": record}

    if current_user.role == Role.STUDENT and record:
        term = _current_term()
        results = Result.query.filter_by(student_id=record.id, term_id=term.id).all() if term else []
        average = round(sum(float(r.total_score) for r in results) / len(results), 1) if results else None
        context.update(term=term, results=results, average=average)

    return render_template("profile/view.html", **context)


@profile_bp.route("/profile/contact", methods=["POST"])
@login_required
def update_contact():
    email = request.form.get("email", "").strip() or None
    phone = request.form.get("phone", "").strip() or None

    if current_user.role != Role.STUDENT and not email and not phone:
        flash("Please leave at least an email or phone number on file — you'll need one of them to sign in.", "danger")
        return redirect(url_for("profile.view_profile"))

    if email and User.query.filter(User.email == email, User.id != current_user.id).first():
        flash("That email is already in use by another account.", "danger")
        return redirect(url_for("profile.view_profile"))

    if phone and User.query.filter(User.phone == phone, User.id != current_user.id).first():
        flash("That phone number is already in use by another account.", "danger")
        return redirect(url_for("profile.view_profile"))

    current_user.email = email
    current_user.phone = phone

    log_action(
        action="profile.contact_updated",
        entity_type="User",
        entity_id=current_user.id,
        description=f"{current_user.full_name} updated their contact details",
    )
    db.session.commit()

    flash("Contact details updated.", "success")
    return redirect(url_for("profile.view_profile"))


@profile_bp.route("/profile/photo", methods=["POST"])
@login_required
def upload_photo():
    record = _profile_record()
    if record is None:
        flash("Your account type doesn't support a profile photo.", "warning")
        return redirect(url_for("profile.view_profile"))

    try:
        new_path = save_profile_photo(request.files.get("photo"), old_relative_path=record.photo_path)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("profile.view_profile"))

    record.photo_path = new_path
    log_action(
        action="profile.photo_updated",
        entity_type=type(record).__name__,
        entity_id=record.id,
        description=f"{current_user.full_name} updated their profile photo",
    )
    db.session.commit()

    flash("Photo updated.", "success")
    return redirect(url_for("profile.view_profile"))


@profile_bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash("Your current password is incorrect.", "danger")
        return redirect(url_for("profile.view_profile"))

    if len(new_password) < 8:
        flash("New password must be at least 8 characters.", "danger")
        return redirect(url_for("profile.view_profile"))

    if new_password != confirm_password:
        flash("New password and confirmation don't match.", "danger")
        return redirect(url_for("profile.view_profile"))

    current_user.set_password(new_password)
    log_action(
        action="profile.password_changed",
        entity_type="User",
        entity_id=current_user.id,
        description=f"{current_user.full_name} changed their password",
    )
    db.session.commit()

    flash("Password changed.", "success")
    return redirect(url_for("profile.view_profile"))


@profile_bp.route("/profile/results/download")
@login_required
def download_results():
    if current_user.role != Role.STUDENT or not current_user.student_profile:
        from flask import abort
        abort(403)

    student = current_user.student_profile
    term = _current_term()
    if not term:
        flash("No current term is set yet — there's nothing to download.", "warning")
        return redirect(url_for("profile.view_profile"))

    results = Result.query.filter_by(student_id=student.id, term_id=term.id).all()
    if not results:
        flash("No results have been entered for this term yet.", "warning")
        return redirect(url_for("profile.view_profile"))

    average = round(sum(float(r.total_score) for r in results) / len(results), 1)

    photo_full_path = None
    if student.photo_path:
        candidate = os.path.join(current_app.config["UPLOAD_FOLDER"], os.path.relpath(student.photo_path, "uploads"))
        if os.path.isfile(candidate):
            photo_full_path = candidate

    pdf_buf = build_result_pdf(student, term, results, average, photo_full_path=photo_full_path)

    log_action(
        action="profile.results_downloaded",
        entity_type="Student",
        entity_id=student.id,
        description=f"{current_user.full_name} downloaded their {term.name} result slip",
    )
    db.session.commit()

    filename = f"{student.admission_number}-{term.name.replace(' ', '-')}-result.pdf"
    return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name=filename)
