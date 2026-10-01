from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role, User
from app.models.people import Staff
from app.models.duty import Duty, DutyAssignment
from app.models.leave import LeaveRequest, LeaveStatus
from app.utils.decorators import roles_required, permission_required
from app.utils.permissions import has_permission
from app.utils.audit import log_action
from app.utils.timeutils import local_today

duties_bp = Blueprint("duties", __name__, template_folder="../../templates/duties")

MANAGER_ROLES = (Role.OWNER, Role.ADMIN)
STAFF_ROLES = (Role.ADMIN, Role.ACCOUNTANT, Role.TEACHER)


def roster_access_required(view):
    """The roster is visible to anyone who can view it OR manage it —
    someone allowed to assign duties obviously needs to see them."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not (has_permission(current_user, "duties.view") or has_permission(current_user, "duties.manage")):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# ------------------------------------------------------------ helpers

def _parse_date(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_time(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return False  # distinguishes "bad input" from "left blank"


def _fmt_range(a):
    if a.start_date == a.end_date:
        return a.start_date.strftime("%d %b %Y")
    return f"{a.start_date.strftime('%d %b')} – {a.end_date.strftime('%d %b %Y')}"


def _overlapping_leaves(staff_id, start, end):
    return LeaveRequest.query.filter(
        LeaveRequest.staff_id == staff_id,
        LeaveRequest.status == LeaveStatus.APPROVED,
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    ).all()


def _leave_conflicts(assignments, today):
    """{assignment_id: LeaveRequest} for upcoming/current assignments whose
    dates overlap that person's approved leave."""
    live = [a for a in assignments if a.end_date >= today]
    if not live:
        return {}
    staff_ids = {a.staff_id for a in live}
    leaves = LeaveRequest.query.filter(
        LeaveRequest.status == LeaveStatus.APPROVED,
        LeaveRequest.staff_id.in_(staff_ids),
        LeaveRequest.end_date >= today,
    ).all()
    out = {}
    for a in live:
        for lv in leaves:
            if lv.staff_id == a.staff_id and lv.start_date <= a.end_date and lv.end_date >= a.start_date:
                out[a.id] = lv
                break
    return out


def _read_assignment_form(multi_staff=True):
    """Returns (values dict, error string or None)."""
    duty = Duty.query.get(request.form.get("duty_id", type=int) or 0)
    if multi_staff:
        staff_ids = [int(x) for x in request.form.getlist("staff_ids") if x.isdigit()]
    else:
        sid = request.form.get("staff_id", type=int)
        staff_ids = [sid] if sid else []

    start = _parse_date(request.form.get("start_date"))
    end = _parse_date(request.form.get("end_date")) or start
    start_time = _parse_time(request.form.get("start_time"))
    end_time = _parse_time(request.form.get("end_time"))
    notes = request.form.get("notes", "").strip()[:255] or None

    if not duty:
        return None, "Choose a duty."
    if not staff_ids:
        return None, "Choose at least one staff member."
    if not start:
        return None, "Choose the date the duty starts."
    if end < start:
        return None, "The end date can't be before the start date."
    if start_time is False or end_time is False:
        return None, "Times should look like 07:30."
    if start_time and end_time and end_time <= start_time:
        return None, "The end time must be after the start time."

    staff = Staff.query.filter(Staff.id.in_(staff_ids), Staff.is_active.is_(True)).all()
    if len(staff) != len(set(staff_ids)):
        return None, "One or more of the selected staff members isn't active."

    return {
        "duty": duty, "staff": staff, "start": start, "end": end,
        "start_time": start_time, "end_time": end_time, "notes": notes,
    }, None


def _assignable_staff():
    return (
        Staff.query.filter(Staff.is_active.is_(True))
        .join(User, Staff.user_id == User.id)
        .order_by(db.func.lower(User.full_name))
        .all()
    )


# -------------------------------------------------------------- roster

@duties_bp.route("/duties")
@login_required
@roles_required(*MANAGER_ROLES)
@roster_access_required
def roster():
    today = local_today()
    when = request.args.get("when", "active")
    duty_id = request.args.get("duty_id", type=int)
    staff_id = request.args.get("staff_id", type=int)

    query = DutyAssignment.query
    if duty_id:
        query = query.filter_by(duty_id=duty_id)
    if staff_id:
        query = query.filter_by(staff_id=staff_id)
    if when == "past":
        query = query.filter(DutyAssignment.end_date < today)
    elif when == "all":
        pass
    else:
        when = "active"
        query = query.filter(DutyAssignment.end_date >= today)

    assignments = query.order_by(DutyAssignment.start_date, DutyAssignment.id).all()
    if when == "past":
        assignments.reverse()

    on_duty_today = (
        DutyAssignment.query.filter(DutyAssignment.start_date <= today, DutyAssignment.end_date >= today)
        .order_by(DutyAssignment.start_time, DutyAssignment.id).all()
    )

    return render_template(
        "duties/roster.html",
        assignments=assignments, today=today, when=when,
        duty_id=duty_id, staff_id=staff_id,
        duties=Duty.query.order_by(Duty.title).all(),
        staff_options=_assignable_staff(),
        on_duty_today=on_duty_today,
        conflicts=_leave_conflicts(assignments, today),
        can_manage=has_permission(current_user, "duties.manage"),
    )


# ------------------------------------------------- duty types (define)

@duties_bp.route("/duties/types", methods=["GET", "POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required("duties.manage")
def duty_types():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        location = request.form.get("location", "").strip() or None

        if not title:
            flash("Give the duty a name.", "danger")
            return redirect(url_for("duties.duty_types"))
        if Duty.query.filter(db.func.lower(Duty.title) == title.lower()).first():
            flash(f"A duty called '{title}' already exists.", "danger")
            return redirect(url_for("duties.duty_types"))

        duty = Duty(title=title, description=description, location=location, created_by_id=current_user.id)
        db.session.add(duty)
        db.session.flush()
        log_action(
            action="duty.created", entity_type="Duty", entity_id=duty.id,
            after={"title": title, "location": location},
            description=f"{current_user.full_name} defined the duty '{title}'",
        )
        db.session.commit()
        flash(f"Duty '{title}' created. You can now assign staff to it.", "success")
        return redirect(url_for("duties.duty_types"))

    duties = Duty.query.order_by(Duty.is_active.desc(), Duty.title).all()
    return render_template("duties/types.html", duties=duties)


@duties_bp.route("/duties/types/<int:duty_id>/edit", methods=["POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required("duties.manage")
def edit_duty(duty_id):
    duty = Duty.query.get_or_404(duty_id)
    title = request.form.get("title", "").strip()
    if not title:
        flash("A duty needs a name.", "danger")
        return redirect(url_for("duties.duty_types"))
    other = Duty.query.filter(db.func.lower(Duty.title) == title.lower(), Duty.id != duty.id).first()
    if other:
        flash(f"Another duty is already called '{title}'.", "danger")
        return redirect(url_for("duties.duty_types"))

    before = {"title": duty.title, "location": duty.location, "is_active": duty.is_active}
    duty.title = title
    duty.description = request.form.get("description", "").strip() or None
    duty.location = request.form.get("location", "").strip() or None
    duty.is_active = bool(request.form.get("is_active"))

    log_action(
        action="duty.updated", entity_type="Duty", entity_id=duty.id, before=before,
        after={"title": duty.title, "location": duty.location, "is_active": duty.is_active},
        description=f"{current_user.full_name} updated the duty '{duty.title}'",
    )
    db.session.commit()
    flash("Duty updated.", "success")
    return redirect(url_for("duties.duty_types"))


@duties_bp.route("/duties/types/<int:duty_id>/delete", methods=["POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required("duties.manage")
def delete_duty(duty_id):
    duty = Duty.query.get_or_404(duty_id)
    if duty.assignments:
        flash(
            f"'{duty.title}' has {len(duty.assignments)} assignment(s) on record, so it can't be deleted. "
            "Mark it inactive instead to stop it being assigned again.",
            "warning",
        )
        return redirect(url_for("duties.duty_types"))

    title = duty.title
    log_action(
        action="duty.deleted", entity_type="Duty", entity_id=duty.id, before={"title": title},
        description=f"{current_user.full_name} deleted the duty '{title}'",
    )
    db.session.delete(duty)
    db.session.commit()
    flash(f"Duty '{title}' deleted.", "success")
    return redirect(url_for("duties.duty_types"))


# ------------------------------------------------------ assign duties

@duties_bp.route("/duties/assign", methods=["GET", "POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required("duties.manage")
def assign():
    active_duties = Duty.query.filter_by(is_active=True).order_by(Duty.title).all()

    if request.method == "POST":
        values, error = _read_assignment_form(multi_staff=True)
        if error:
            flash(error, "danger")
            return render_template(
                "duties/assign.html", assignment=None, duties=active_duties,
                staff_options=_assignable_staff(), form=request.form,
                selected_staff=set(request.form.getlist("staff_ids")),
            )

        created, skipped, on_leave = [], [], []
        for staff in values["staff"]:
            duplicate = DutyAssignment.query.filter(
                DutyAssignment.duty_id == values["duty"].id,
                DutyAssignment.staff_id == staff.id,
                DutyAssignment.start_date <= values["end"],
                DutyAssignment.end_date >= values["start"],
            ).first()
            if duplicate:
                skipped.append(staff.user.full_name)
                continue

            a = DutyAssignment(
                duty_id=values["duty"].id, staff_id=staff.id,
                start_date=values["start"], end_date=values["end"],
                start_time=values["start_time"], end_time=values["end_time"],
                notes=values["notes"], assigned_by_id=current_user.id,
            )
            db.session.add(a)
            db.session.flush()
            created.append(staff.user.full_name)
            if _overlapping_leaves(staff.id, values["start"], values["end"]):
                on_leave.append(staff.user.full_name)

            log_action(
                action="duty.assigned", entity_type="DutyAssignment", entity_id=a.id,
                after={"duty": values["duty"].title, "staff": staff.user.full_name,
                       "from": str(values["start"]), "to": str(values["end"]),
                       "time": a.time_window_label},
                description=f"{current_user.full_name} assigned {staff.user.full_name} to "
                            f"'{values['duty'].title}' ({_fmt_range(a)}, {a.time_window_label})",
            )
        db.session.commit()

        if created:
            flash(f"'{values['duty'].title}' assigned to {', '.join(created)}.", "success")
        if skipped:
            flash(f"Skipped {', '.join(skipped)} — already assigned to this duty over overlapping dates.", "warning")
        if on_leave:
            flash(f"Note: {', '.join(on_leave)} {'has' if len(on_leave) == 1 else 'have'} approved leave during these dates.", "warning")
        return redirect(url_for("duties.roster"))

    return render_template(
        "duties/assign.html", assignment=None, duties=active_duties,
        staff_options=_assignable_staff(), form=request.args, selected_staff=set(),
    )


@duties_bp.route("/duties/assignments/<int:assignment_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required("duties.manage")
def edit_assignment(assignment_id):
    a = DutyAssignment.query.get_or_404(assignment_id)
    active_duties = Duty.query.filter((Duty.is_active.is_(True)) | (Duty.id == a.duty_id)).order_by(Duty.title).all()

    if request.method == "POST":
        values, error = _read_assignment_form(multi_staff=False)
        if error:
            flash(error, "danger")
            return render_template(
                "duties/assign.html", assignment=a, duties=active_duties,
                staff_options=_assignable_staff(), form=request.form, selected_staff=set(),
            )

        staff = values["staff"][0]
        clash = DutyAssignment.query.filter(
            DutyAssignment.id != a.id,
            DutyAssignment.duty_id == values["duty"].id,
            DutyAssignment.staff_id == staff.id,
            DutyAssignment.start_date <= values["end"],
            DutyAssignment.end_date >= values["start"],
        ).first()
        if clash:
            flash(f"{staff.user.full_name} already has this duty over overlapping dates.", "danger")
            return render_template(
                "duties/assign.html", assignment=a, duties=active_duties,
                staff_options=_assignable_staff(), form=request.form, selected_staff=set(),
            )

        before = {"duty": a.duty.title, "staff": a.staff.user.full_name, "from": str(a.start_date),
                  "to": str(a.end_date), "time": a.time_window_label}
        a.duty_id = values["duty"].id
        a.staff_id = staff.id
        a.start_date, a.end_date = values["start"], values["end"]
        a.start_time, a.end_time = values["start_time"], values["end_time"]
        a.notes = values["notes"]
        db.session.flush()

        log_action(
            action="duty.assignment_updated", entity_type="DutyAssignment", entity_id=a.id, before=before,
            after={"duty": values["duty"].title, "staff": staff.user.full_name, "from": str(a.start_date),
                   "to": str(a.end_date), "time": a.time_window_label},
            description=f"{current_user.full_name} updated {staff.user.full_name}'s '{values['duty'].title}' assignment",
        )
        db.session.commit()
        flash("Assignment updated.", "success")
        if _overlapping_leaves(staff.id, a.start_date, a.end_date):
            flash(f"Note: {staff.user.full_name} has approved leave during these dates.", "warning")
        return redirect(url_for("duties.roster"))

    form = {
        "duty_id": a.duty_id, "staff_id": a.staff_id,
        "start_date": a.start_date.isoformat(), "end_date": a.end_date.isoformat(),
        "start_time": a.start_time.strftime("%H:%M") if a.start_time else "",
        "end_time": a.end_time.strftime("%H:%M") if a.end_time else "",
        "notes": a.notes or "",
    }
    return render_template(
        "duties/assign.html", assignment=a, duties=active_duties,
        staff_options=_assignable_staff(), form=form, selected_staff=set(),
    )


@duties_bp.route("/duties/assignments/<int:assignment_id>/delete", methods=["POST"])
@login_required
@roles_required(*MANAGER_ROLES)
@permission_required("duties.manage")
def delete_assignment(assignment_id):
    a = DutyAssignment.query.get_or_404(assignment_id)
    summary = f"{a.staff.user.full_name} — '{a.duty.title}' ({_fmt_range(a)})"
    log_action(
        action="duty.unassigned", entity_type="DutyAssignment", entity_id=a.id,
        before={"duty": a.duty.title, "staff": a.staff.user.full_name, "from": str(a.start_date), "to": str(a.end_date)},
        description=f"{current_user.full_name} removed the assignment {summary}",
    )
    db.session.delete(a)
    db.session.commit()
    flash("Assignment removed.", "success")
    return redirect(url_for("duties.roster"))


# ---------------------------------------------------- staff: my duties

@duties_bp.route("/duties/my")
@login_required
@roles_required(*STAFF_ROLES)
def my_duties():
    staff = current_user.staff_profile
    if not staff:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    today = local_today()
    mine = (
        DutyAssignment.query.filter_by(staff_id=staff.id)
        .order_by(DutyAssignment.start_date, DutyAssignment.id).all()
    )
    return render_template(
        "duties/my_duties.html",
        current=[a for a in mine if a.state_on(today) == "current"],
        upcoming=[a for a in mine if a.state_on(today) == "upcoming"],
        past=list(reversed([a for a in mine if a.state_on(today) == "past"]))[:15],
        today=today,
    )
