from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.user import Role, User
from app.models.people import Student, StudentStatus, ParentProfile, StudentGuardian
from app.models.academic import AcademicSession, ClassArm
from app.utils.decorators import roles_required, permission_required
from app.utils.audit import log_action
from app.utils.permissions import has_permission

students_bp = Blueprint("students", __name__, template_folder="../../templates/students")

EDITOR_ROLES = (Role.OWNER, Role.ADMIN)
VIEWER_ROLES = (Role.OWNER, Role.ADMIN, Role.ACCOUNTANT, Role.TEACHER)


def _current_session():
    return AcademicSession.query.filter_by(is_current=True).first()


def _generate_admission_number():
    session = _current_session()
    year_tag = session.name.split("/")[0] if session else str(datetime.utcnow().year)
    prefix = f"STU/{year_tag}/"

    # Base the next number on the highest existing suffix for this year,
    # not on a raw row count — count-based numbering collides whenever a
    # form sits open across two submissions (or two tabs) before either commits.
    existing = Student.query.filter(Student.admission_number.like(f"{prefix}%")).all()
    max_seq = 0
    for s in existing:
        suffix = s.admission_number.replace(prefix, "")
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))

    candidate = f"{prefix}{max_seq + 1:04d}"
    while Student.query.filter_by(admission_number=candidate).first():
        max_seq += 1
        candidate = f"{prefix}{max_seq + 1:04d}"
    return candidate


@students_bp.route("/students")
@login_required
@roles_required(*VIEWER_ROLES)
@permission_required('students.view')
def list_students():
    status_filter = request.args.get("status", StudentStatus.ACTIVE)
    class_arm_filter = request.args.get("class_arm_id", type=int)
    search = request.args.get("q", "").strip()

    query = Student.query
    if status_filter and status_filter != "all":
        query = query.filter_by(status=status_filter)
    if class_arm_filter:
        query = query.filter_by(class_arm_id=class_arm_filter)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Student.full_name.ilike(like)) | (Student.admission_number.ilike(like))
        )

    students = query.order_by(Student.full_name).all()
    class_arms = ClassArm.query.join(AcademicSession).filter(AcademicSession.is_current.is_(True)).all()

    return render_template(
        "students/list.html",
        students=students,
        class_arms=class_arms,
        status_filter=status_filter,
        class_arm_filter=class_arm_filter,
        search=search,
        statuses=[StudentStatus.ACTIVE, StudentStatus.GRADUATED, StudentStatus.WITHDRAWN,
                  StudentStatus.SUSPENDED, StudentStatus.ARCHIVED],
    )


@students_bp.route("/students/new", methods=["GET", "POST"])
@login_required
@roles_required(*EDITOR_ROLES)
@permission_required('students.manage')
def create_student():
    class_arms = ClassArm.query.join(AcademicSession).filter(AcademicSession.is_current.is_(True)).all()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        if not full_name:
            flash("Student full name is required.", "danger")
            return render_template("students/form.html", student=None, class_arms=class_arms, form=request.form)

        admission_number = request.form.get("admission_number", "").strip() or _generate_admission_number()

        # The number shown on the form was suggested at page-load time. If
        # someone else registered a student in the meantime (or the same
        # form was submitted twice), that suggestion may now be taken —
        # silently regenerate rather than crashing with a 500.
        if Student.query.filter_by(admission_number=admission_number).first():
            admission_number = _generate_admission_number()

        dob_raw = request.form.get("date_of_birth")
        dob = datetime.strptime(dob_raw, "%Y-%m-%d").date() if dob_raw else None

        class_arm_id = request.form.get("class_arm_id", type=int)

        student = Student(
            full_name=full_name,
            admission_number=admission_number,
            date_of_birth=dob,
            gender=request.form.get("gender"),
            class_arm_id=class_arm_id,
            previous_school=request.form.get("previous_school"),
            address=request.form.get("address"),
            medical_info=request.form.get("medical_info"),
            status=StudentStatus.ACTIVE,
        )
        db.session.add(student)
        try:
            db.session.flush()
        except IntegrityError:
            # True race condition: two requests generated/submitted the same
            # number at almost the same instant. Roll back and let the admin
            # retry rather than showing a raw 500 error page.
            db.session.rollback()
            flash("That admission number was just taken by another registration. Please try again.", "warning")
            return render_template("students/form.html", student=None, class_arms=class_arms, form=request.form)

        # Optional guardian — creates a Parent user + profile if details given
        guardian_name = request.form.get("guardian_full_name", "").strip()
        guardian_phone = request.form.get("guardian_phone", "").strip()
        if guardian_name and guardian_phone:
            parent_user = User.query.filter_by(phone=guardian_phone).first()
            if not parent_user:
                parent_user = User(
                    role=Role.PARENT,
                    full_name=guardian_name,
                    phone=guardian_phone,
                    email=request.form.get("guardian_email") or None,
                )
                parent_user.set_password("ChangeMe123!")  # parent should reset on first login
                db.session.add(parent_user)
                db.session.flush()

                parent_profile = ParentProfile(user_id=parent_user.id)
                db.session.add(parent_profile)
                db.session.flush()
            else:
                parent_profile = parent_user.parent_profile
                if not parent_profile:
                    parent_profile = ParentProfile(user_id=parent_user.id)
                    db.session.add(parent_profile)
                    db.session.flush()

            link = StudentGuardian(
                student_id=student.id,
                parent_profile_id=parent_profile.id,
                relationship_type=request.form.get("relationship_type", "Guardian"),
                is_primary_contact=True,
            )
            db.session.add(link)

        log_action(
            action="student.created",
            entity_type="Student",
            entity_id=student.id,
            after={"admission_number": student.admission_number, "full_name": student.full_name},
            description=f"{current_user.full_name} registered new student {student.full_name} ({student.admission_number})",
        )
        db.session.commit()

        flash(f"Student {student.full_name} registered with admission number {student.admission_number}.", "success")
        return redirect(url_for("students.view_student", student_id=student.id))

    return render_template(
        "students/form.html",
        student=None,
        class_arms=class_arms,
        form={"admission_number": _generate_admission_number()},
    )


@students_bp.route("/students/<int:student_id>")
@login_required
@roles_required(*VIEWER_ROLES)
@permission_required('students.view')
def view_student(student_id):
    student = Student.query.get_or_404(student_id)

    attendance_summary = None
    if has_permission(current_user, "attendance.student.view"):
        from datetime import date, timedelta
        from app.models.attendance import StudentAttendance, AttendanceStatus
        since = date.today() - timedelta(days=30)
        records = StudentAttendance.query.filter(
            StudentAttendance.student_id == student.id, StudentAttendance.date >= since
        ).all()
        if records:
            present = sum(1 for r in records if r.status == AttendanceStatus.PRESENT)
            attendance_summary = {
                "total": len(records),
                "present": present,
                "rate": round(present / len(records) * 100, 1),
            }

    return render_template("students/view.html", student=student, attendance_summary=attendance_summary)


@students_bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required(*EDITOR_ROLES)
@permission_required('students.manage')
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)
    class_arms = ClassArm.query.join(AcademicSession).filter(AcademicSession.is_current.is_(True)).all()

    if request.method == "POST":
        before = {
            "full_name": student.full_name,
            "class_arm_id": student.class_arm_id,
            "status": student.status,
        }

        student.full_name = request.form.get("full_name", student.full_name).strip()
        dob_raw = request.form.get("date_of_birth")
        student.date_of_birth = datetime.strptime(dob_raw, "%Y-%m-%d").date() if dob_raw else student.date_of_birth
        student.gender = request.form.get("gender")
        student.class_arm_id = request.form.get("class_arm_id", type=int)
        student.previous_school = request.form.get("previous_school")
        student.address = request.form.get("address")
        student.medical_info = request.form.get("medical_info")

        log_action(
            action="student.updated",
            entity_type="Student",
            entity_id=student.id,
            before=before,
            after={"full_name": student.full_name, "class_arm_id": student.class_arm_id, "status": student.status},
            description=f"{current_user.full_name} updated student {student.full_name}",
        )
        db.session.commit()

        flash("Student record updated.", "success")
        return redirect(url_for("students.view_student", student_id=student.id))

    return render_template("students/form.html", student=student, class_arms=class_arms, form=None)


@students_bp.route("/students/<int:student_id>/status", methods=["POST"])
@login_required
@roles_required(*EDITOR_ROLES)
@permission_required('students.manage')
def change_status(student_id):
    student = Student.query.get_or_404(student_id)
    new_status = request.form.get("status")

    valid_statuses = [StudentStatus.ACTIVE, StudentStatus.GRADUATED, StudentStatus.WITHDRAWN,
                       StudentStatus.SUSPENDED, StudentStatus.ARCHIVED]
    if new_status not in valid_statuses:
        flash("Invalid status.", "danger")
        return redirect(url_for("students.view_student", student_id=student.id))

    old_status = student.status
    student.status = new_status

    log_action(
        action="student.status_changed",
        entity_type="Student",
        entity_id=student.id,
        before={"status": old_status},
        after={"status": new_status},
        description=f"{current_user.full_name} changed {student.full_name}'s status from {old_status} to {new_status}",
    )
    db.session.commit()

    flash(f"Status updated to {new_status}.", "success")
    return redirect(url_for("students.view_student", student_id=student.id))


DEFAULT_STUDENT_PASSWORD = "Student123!"


@students_bp.route("/students/<int:student_id>/create-login", methods=["POST"])
@login_required
@roles_required(*EDITOR_ROLES)
@permission_required('students.manage')
def create_login(student_id):
    student = Student.query.get_or_404(student_id)

    if student.user_id:
        flash(f"{student.full_name} already has a login.", "warning")
        return redirect(url_for("students.view_student", student_id=student.id))

    user = User(role=Role.STUDENT, full_name=student.full_name)
    user.set_password(DEFAULT_STUDENT_PASSWORD)
    db.session.add(user)
    db.session.flush()

    student.user_id = user.id

    log_action(
        action="student.login_created",
        entity_type="Student",
        entity_id=student.id,
        description=f"{current_user.full_name} created a login for {student.full_name}",
    )
    db.session.commit()

    flash(
        f"Login created for {student.full_name}. They sign in with their admission number "
        f"({student.admission_number}) as username and password: {DEFAULT_STUDENT_PASSWORD}",
        "success",
    )
    return redirect(url_for("students.view_student", student_id=student.id))


@students_bp.route("/students/<int:student_id>/reset-login-password", methods=["POST"])
@login_required
@roles_required(*EDITOR_ROLES)
@permission_required('students.manage')
def reset_login_password(student_id):
    student = Student.query.get_or_404(student_id)

    if not student.user_id:
        flash("This student doesn't have a login yet.", "warning")
        return redirect(url_for("students.view_student", student_id=student.id))

    student.user.set_password(DEFAULT_STUDENT_PASSWORD)
    student.user.failed_login_count = 0
    student.user.locked_until = None

    log_action(
        action="student.login_password_reset",
        entity_type="Student",
        entity_id=student.id,
        description=f"{current_user.full_name} reset the login password for {student.full_name}",
    )
    db.session.commit()

    flash(f"Password reset to: {DEFAULT_STUDENT_PASSWORD}", "warning")
    return redirect(url_for("students.view_student", student_id=student.id))
