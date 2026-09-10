import secrets
import string
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.user import Role, User
from app.models.people import Staff
from app.utils.decorators import roles_required, permission_required
from app.utils.audit import log_action

staff_bp = Blueprint("staff", __name__, template_folder="../../templates/staff")

# Owner/Admin manage staff. Only Owner/Admin roles can be assigned here —
# creating another Owner account is intentionally not exposed in this UI;
# that stays a seed/database-level action to avoid accidental privilege escalation.
ASSIGNABLE_ROLES = (Role.ADMIN, Role.ACCOUNTANT, Role.TEACHER)
MANAGER_ROLES = (Role.OWNER, Role.ADMIN)

DEFAULT_PASSWORD = "ChangeMe123!"


def _generate_staff_id():
    prefix = f"STF/{datetime.utcnow().year}/"
    existing = Staff.query.filter(Staff.staff_id_number.like(f"{prefix}%")).all()
    max_seq = 0
    for s in existing:
        suffix = (s.staff_id_number or "").replace(prefix, "")
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    return f"{prefix}{max_seq + 1:04d}"


@staff_bp.route("/staff")
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required('staff.view')
def list_staff():
    role_filter = request.args.get("role", "all")
    search = request.args.get("q", "").strip()

    query = Staff.query.join(User)
    if role_filter != "all":
        query = query.filter(User.role == role_filter)
    if search:
        like = f"%{search}%"
        query = query.filter((User.full_name.ilike(like)) | (Staff.staff_id_number.ilike(like)))

    staff_members = query.order_by(User.full_name).all()
    return render_template(
        "staff/list.html",
        staff_members=staff_members,
        role_filter=role_filter,
        search=search,
        roles=ASSIGNABLE_ROLES,
    )


@staff_bp.route("/staff/new", methods=["GET", "POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required('staff.manage')
def create_staff():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role")
        email = request.form.get("email", "").strip() or None
        phone = request.form.get("phone", "").strip() or None
        designation = request.form.get("designation", "").strip()

        if not full_name or role not in ASSIGNABLE_ROLES:
            flash("Full name and a valid role are required.", "danger")
            return render_template("staff/form.html", staff=None, roles=ASSIGNABLE_ROLES, form=request.form)

        if not email and not phone:
            flash("Provide at least an email or phone number so this person can log in.", "danger")
            return render_template("staff/form.html", staff=None, roles=ASSIGNABLE_ROLES, form=request.form)

        if email and User.query.filter_by(email=email).first():
            flash("A user with that email already exists.", "danger")
            return render_template("staff/form.html", staff=None, roles=ASSIGNABLE_ROLES, form=request.form)
        if phone and User.query.filter_by(phone=phone).first():
            flash("A user with that phone number already exists.", "danger")
            return render_template("staff/form.html", staff=None, roles=ASSIGNABLE_ROLES, form=request.form)

        user = User(role=role, full_name=full_name, email=email, phone=phone)
        user.set_password(DEFAULT_PASSWORD)
        db.session.add(user)

        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            flash("That email or phone is already registered. Please use different contact details.", "danger")
            return render_template("staff/form.html", staff=None, roles=ASSIGNABLE_ROLES, form=request.form)

        staff = Staff(
            user_id=user.id,
            staff_id_number=_generate_staff_id(),
            designation=designation,
            date_employed=datetime.utcnow().date(),
            is_active=True,
        )
        db.session.add(staff)
        db.session.flush()

        log_action(
            action="staff.created",
            entity_type="Staff",
            entity_id=staff.id,
            after={"full_name": full_name, "role": role, "staff_id": staff.staff_id_number},
            description=f"{current_user.full_name} created a {role} account for {full_name} ({staff.staff_id_number})",
        )
        db.session.commit()

        flash(
            f"Staff account created for {full_name} ({staff.staff_id_number}). "
            f"Default password: {DEFAULT_PASSWORD} — share this with them securely and ask them to change it.",
            "success",
        )
        return redirect(url_for("staff.view_staff", staff_id=staff.id))

    return render_template("staff/form.html", staff=None, roles=ASSIGNABLE_ROLES, form=None)


@staff_bp.route("/staff/<int:staff_id>")
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required('staff.view')
def view_staff(staff_id):
    staff = Staff.query.get_or_404(staff_id)
    return render_template("staff/view.html", staff=staff)


@staff_bp.route("/staff/<int:staff_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required('staff.manage')
def edit_staff(staff_id):
    staff = Staff.query.get_or_404(staff_id)

    if request.method == "POST":
        before = {"full_name": staff.user.full_name, "designation": staff.designation}

        staff.user.full_name = request.form.get("full_name", staff.user.full_name).strip()
        staff.designation = request.form.get("designation", staff.designation).strip()

        new_email = request.form.get("email", "").strip() or None
        new_phone = request.form.get("phone", "").strip() or None

        if new_email and new_email != staff.user.email and User.query.filter_by(email=new_email).first():
            flash("That email is already in use by another account.", "danger")
            return render_template("staff/form.html", staff=staff, roles=ASSIGNABLE_ROLES, form=None)
        if new_phone and new_phone != staff.user.phone and User.query.filter_by(phone=new_phone).first():
            flash("That phone number is already in use by another account.", "danger")
            return render_template("staff/form.html", staff=staff, roles=ASSIGNABLE_ROLES, form=None)

        staff.user.email = new_email
        staff.user.phone = new_phone

        log_action(
            action="staff.updated",
            entity_type="Staff",
            entity_id=staff.id,
            before=before,
            after={"full_name": staff.user.full_name, "designation": staff.designation},
            description=f"{current_user.full_name} updated staff record for {staff.user.full_name}",
        )
        db.session.commit()

        flash("Staff record updated.", "success")
        return redirect(url_for("staff.view_staff", staff_id=staff.id))

    return render_template("staff/form.html", staff=staff, roles=ASSIGNABLE_ROLES, form=None)


@staff_bp.route("/staff/<int:staff_id>/toggle-active", methods=["POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required('staff.manage')
def toggle_active(staff_id):
    staff = Staff.query.get_or_404(staff_id)
    staff.is_active = not staff.is_active
    staff.user.is_active = staff.is_active

    log_action(
        action="staff.status_changed",
        entity_type="Staff",
        entity_id=staff.id,
        after={"is_active": staff.is_active},
        description=f"{current_user.full_name} {'reactivated' if staff.is_active else 'deactivated'} "
                     f"{staff.user.full_name}'s account",
    )
    db.session.commit()

    flash(f"{staff.user.full_name}'s account is now {'active' if staff.is_active else 'inactive'}.", "success")
    return redirect(url_for("staff.view_staff", staff_id=staff.id))


@staff_bp.route("/staff/<int:staff_id>/reset-password", methods=["POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required('staff.manage')
def reset_password(staff_id):
    staff = Staff.query.get_or_404(staff_id)
    temp_password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
    staff.user.set_password(temp_password)
    staff.user.failed_login_count = 0
    staff.user.locked_until = None

    log_action(
        action="staff.password_reset",
        entity_type="Staff",
        entity_id=staff.id,
        description=f"{current_user.full_name} reset the password for {staff.user.full_name}",
    )
    db.session.commit()

    flash(f"Password reset. New temporary password for {staff.user.full_name}: {temp_password} — share it securely.", "warning")
    return redirect(url_for("staff.view_staff", staff_id=staff.id))
