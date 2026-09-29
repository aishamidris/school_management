from datetime import datetime, date as date_cls, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role
from app.models.academic import AcademicSession, ClassArm
from app.models.people import Student, StudentStatus, Staff
from app.models.attendance import StudentAttendance, StaffAttendance, AttendanceStatus
from app.models.settings import SchoolSettings
from app.utils.decorators import roles_required, permission_required
from app.utils.permissions import has_permission
from app.utils.audit import log_action
from app.utils.geo import haversine_distance_m

attendance_bp = Blueprint("attendance", __name__, template_folder="../../templates/attendance")

MARKER_ROLES = (Role.OWNER, Role.ADMIN, Role.TEACHER)
STAFF_ROLES = (Role.OWNER, Role.ADMIN, Role.ACCOUNTANT, Role.TEACHER)
ADMIN_ROLES = (Role.OWNER, Role.ADMIN)

STATUS_LABELS = {
    AttendanceStatus.PRESENT: "Present",
    AttendanceStatus.ABSENT: "Absent",
    AttendanceStatus.LATE: "Late",
    AttendanceStatus.EXCUSED: "Excused",
}


def _parse_date(raw):
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date_cls.today()


def _evaluate_location(settings, lat, lng, accuracy):
    """Returns (distance_m, verified) for a submitted lat/lng against the
    configured school location. verified is None when there's nothing to
    judge yet (no school location configured, or browser gave nothing).

    The device's own reported GPS accuracy is added to the allowed radius
    (capped at 100 m) so a normal, slightly-imprecise reading near the
    boundary isn't wrongly flagged as off-site."""
    if not settings.is_configured:
        return None, None
    if lat is None or lng is None:
        return None, False

    distance = haversine_distance_m(settings.latitude, settings.longitude, lat, lng)
    tolerance = settings.checkin_radius_m + min(accuracy or 0, 100)
    verified = distance <= tolerance
    return round(distance), verified


def _read_location_form():
    """Pulls optional lat/lng/accuracy out of a check-in/out POST. Any of
    them can be missing (JS geolocation may have failed or been denied)."""
    try:
        lat = float(request.form.get("latitude"))
        lng = float(request.form.get("longitude"))
    except (TypeError, ValueError):
        return None, None, None
    try:
        accuracy = float(request.form.get("accuracy"))
    except (TypeError, ValueError):
        accuracy = None
    return lat, lng, accuracy


# ---------------- Student attendance ----------------

@attendance_bp.route("/attendance/students")
@login_required
@roles_required(*MARKER_ROLES)
@permission_required("attendance.student.view")
def class_picker():
    class_arms = ClassArm.query.join(AcademicSession).filter(AcademicSession.is_current.is_(True)).all()

    # A teacher only marks attendance for the class(es) they're the
    # assigned Class Teacher of — not every class they teach a subject in.
    if current_user.role == Role.TEACHER and current_user.staff_profile:
        class_arms = [a for a in class_arms if a.class_teacher_id == current_user.staff_profile.id]

    return render_template("attendance/class_picker.html", class_arms=class_arms)


@attendance_bp.route("/attendance/students/<int:class_arm_id>", methods=["GET", "POST"])
@login_required
@roles_required(*MARKER_ROLES)
@permission_required("attendance.student.view")
def mark_attendance(class_arm_id):
    class_arm = ClassArm.query.get_or_404(class_arm_id)

    # Belt-and-braces: a teacher hitting this URL directly for a class
    # they aren't the Class Teacher of is blocked, not just hidden from
    # the picker above.
    if current_user.role == Role.TEACHER:
        if not current_user.staff_profile or class_arm.class_teacher_id != current_user.staff_profile.id:
            abort(403)

    selected_date = _parse_date(request.values.get("date"))
    can_edit = has_permission(current_user, "attendance.student.mark")

    students = (
        Student.query.filter_by(class_arm_id=class_arm.id, status=StudentStatus.ACTIVE)
        .order_by(Student.full_name)
        .all()
    )

    if request.method == "POST":
        if not can_edit:
            abort(403)

        saved = 0
        for student in students:
            status = request.form.get(f"status_{student.id}")
            if not status or status not in STATUS_LABELS:
                continue

            record = StudentAttendance.query.filter_by(student_id=student.id, date=selected_date).first()
            if record:
                record.status = status
                record.recorded_by_id = current_user.id
                record.class_arm_id = class_arm.id
            else:
                record = StudentAttendance(
                    student_id=student.id,
                    class_arm_id=class_arm.id,
                    date=selected_date,
                    status=status,
                    recorded_by_id=current_user.id,
                )
                db.session.add(record)
            saved += 1

        log_action(
            action="attendance.student_marked",
            entity_type="ClassArm",
            entity_id=class_arm.id,
            after={"date": str(selected_date), "count": saved},
            description=f"{current_user.full_name} recorded attendance for {saved} student(s) in "
                         f"{class_arm.display_name} on {selected_date}",
        )
        db.session.commit()

        flash(f"Attendance saved for {saved} student(s) on {selected_date.strftime('%d %b %Y')}.", "success")
        return redirect(url_for("attendance.mark_attendance", class_arm_id=class_arm.id, date=selected_date))

    existing = {
        r.student_id: r
        for r in StudentAttendance.query.filter_by(class_arm_id=class_arm.id, date=selected_date).all()
    }

    present_count = sum(1 for r in existing.values() if r.status == AttendanceStatus.PRESENT)

    return render_template(
        "attendance/mark.html",
        class_arm=class_arm,
        students=students,
        existing=existing,
        selected_date=selected_date,
        statuses=STATUS_LABELS,
        present_count=present_count,
        can_edit=can_edit,
        prev_date=(selected_date - timedelta(days=1)).isoformat(),
        next_date=(selected_date + timedelta(days=1)).isoformat(),
    )


# ---------------- Staff self check-in/out ----------------
# Deliberately open to every staff role including accountant — this is
# self-service (marking your own presence), not viewing or marking
# anyone else's attendance, so it isn't gated by the attendance.staff.*
# permissions at all.

@attendance_bp.route("/attendance/my-attendance")
@login_required
@roles_required(*STAFF_ROLES)
def my_attendance():
    if not current_user.staff_profile:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    today = date_cls.today()
    today_record = StaffAttendance.query.filter_by(staff_id=current_user.staff_profile.id, date=today).first()

    history = (
        StaffAttendance.query.filter_by(staff_id=current_user.staff_profile.id)
        .order_by(StaffAttendance.date.desc())
        .limit(30)
        .all()
    )

    return render_template("attendance/my_attendance.html", today_record=today_record, history=history, today=today, settings=SchoolSettings.get())


@attendance_bp.route("/attendance/check-in", methods=["POST"])
@login_required
@roles_required(*STAFF_ROLES)
def check_in():
    staff = current_user.staff_profile
    if not staff:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    today = date_cls.today()
    record = StaffAttendance.query.filter_by(staff_id=staff.id, date=today).first()
    if record and record.check_in:
        flash("You've already checked in today.", "warning")
        return redirect(url_for("attendance.my_attendance"))

    settings = SchoolSettings.get()
    lat, lng, accuracy = _read_location_form()
    distance, verified = _evaluate_location(settings, lat, lng, accuracy)

    if settings.enforce_checkin_location and settings.is_configured and verified is not True:
        if lat is None:
            flash("We couldn't get your location. Please allow location access in your browser and try again.", "danger")
        else:
            flash(f"You appear to be about {distance:,} m from school, which is outside the allowed range. Check-in was not recorded.", "danger")
        return redirect(url_for("attendance.my_attendance"))

    if not record:
        record = StaffAttendance(staff_id=staff.id, date=today, status=AttendanceStatus.PRESENT)
        db.session.add(record)

    record.check_in = datetime.utcnow()
    record.status = AttendanceStatus.PRESENT
    record.check_in_lat = lat
    record.check_in_lng = lng
    record.check_in_accuracy_m = accuracy
    record.check_in_distance_m = distance
    record.check_in_verified = verified

    location_note = ""
    if verified is True:
        location_note = f" (on-site, ~{distance:,} m from school)"
    elif verified is False and distance is not None:
        location_note = f" (off-site, ~{distance:,} m from school)"
    elif verified is False:
        location_note = " (no location provided)"

    log_action(
        action="attendance.staff_checkin",
        entity_type="StaffAttendance",
        entity_id=staff.id,
        description=f"{current_user.full_name} checked in at {record.check_in.strftime('%H:%M')}{location_note}",
    )
    db.session.commit()

    flash("Checked in. Have a good day!", "success")
    return redirect(url_for("attendance.my_attendance"))


@attendance_bp.route("/attendance/check-out", methods=["POST"])
@login_required
@roles_required(*STAFF_ROLES)
def check_out():
    staff = current_user.staff_profile
    if not staff:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    today = date_cls.today()
    record = StaffAttendance.query.filter_by(staff_id=staff.id, date=today).first()
    if not record or not record.check_in:
        flash("You need to check in before you can check out.", "warning")
        return redirect(url_for("attendance.my_attendance"))
    if record.check_out:
        flash("You've already checked out today.", "warning")
        return redirect(url_for("attendance.my_attendance"))

    settings = SchoolSettings.get()
    lat, lng, accuracy = _read_location_form()
    distance, verified = _evaluate_location(settings, lat, lng, accuracy)

    if settings.enforce_checkin_location and settings.is_configured and verified is not True:
        if lat is None:
            flash("We couldn't get your location. Please allow location access in your browser and try again.", "danger")
        else:
            flash(f"You appear to be about {distance:,} m from school, which is outside the allowed range. Check-out was not recorded.", "danger")
        return redirect(url_for("attendance.my_attendance"))

    record.check_out = datetime.utcnow()
    record.check_out_lat = lat
    record.check_out_lng = lng
    record.check_out_accuracy_m = accuracy
    record.check_out_distance_m = distance
    record.check_out_verified = verified

    log_action(
        action="attendance.staff_checkout",
        entity_type="StaffAttendance",
        entity_id=staff.id,
        description=f"{current_user.full_name} checked out at {record.check_out.strftime('%H:%M')}",
    )
    db.session.commit()

    flash("Checked out. See you next time!", "success")
    return redirect(url_for("attendance.my_attendance"))


# ---------------- Admin: staff attendance overview ----------------

@attendance_bp.route("/attendance/staff")
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required("attendance.staff.view")
def staff_overview():
    selected_date = _parse_date(request.args.get("date"))

    all_staff = Staff.query.filter_by(is_active=True).all()
    records = {r.staff_id: r for r in StaffAttendance.query.filter_by(date=selected_date).all()}

    rows = []
    for s in all_staff:
        rows.append({"staff": s, "record": records.get(s.id)})

    present_count = sum(1 for r in rows if r["record"] and r["record"].status == AttendanceStatus.PRESENT)

    return render_template(
        "attendance/staff_overview.html",
        rows=rows,
        selected_date=selected_date,
        present_count=present_count,
        total_staff=len(all_staff),
    )


# ---------------- Admin: check-in location settings ----------------

@attendance_bp.route("/attendance/settings/location", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required("attendance.settings")
def location_settings():
    settings = SchoolSettings.get()

    if request.method == "POST":
        try:
            lat = float(request.form.get("latitude"))
            lng = float(request.form.get("longitude"))
        except (TypeError, ValueError):
            flash("Please provide valid latitude and longitude values.", "danger")
            return redirect(url_for("attendance.location_settings"))

        try:
            radius = int(request.form.get("checkin_radius_m", 150))
        except (TypeError, ValueError):
            radius = 150
        radius = max(20, min(radius, 2000))

        settings.latitude = lat
        settings.longitude = lng
        settings.checkin_radius_m = radius
        settings.enforce_checkin_location = bool(request.form.get("enforce_checkin_location"))

        log_action(
            action="attendance.location_settings_updated",
            entity_type="SchoolSettings",
            entity_id=settings.id,
            description=f"{current_user.full_name} updated the school check-in location (radius {radius} m, enforced={settings.enforce_checkin_location})",
        )
        db.session.commit()

        flash("Check-in location settings saved.", "success")
        return redirect(url_for("attendance.location_settings"))

    return render_template("attendance/location_settings.html", settings=settings)
