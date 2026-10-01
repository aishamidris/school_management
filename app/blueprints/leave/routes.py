from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role
from app.models.leave import LeaveRequest, LeaveType, LeaveStatus
from app.models.duty import DutyAssignment
from app.utils.decorators import roles_required, permission_required
from app.utils.audit import log_action
from app.utils.timeutils import local_today

leave_bp = Blueprint("leave", __name__, template_folder="../../templates/leave")

STAFF_ROLES = (Role.ADMIN, Role.ACCOUNTANT, Role.TEACHER)
REVIEWER_ROLES = (Role.OWNER, Role.ADMIN)

# A request can be back-dated this far (someone who was ill yesterday can
# still file it), but not further — otherwise old absences could be
# quietly turned into "leave" months later.
BACKDATE_DAYS = 7
MAX_SPAN_DAYS = 365


def _parse_date(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _fmt_range(lv):
    if lv.start_date == lv.end_date:
        return lv.start_date.strftime("%d %b %Y")
    return f"{lv.start_date.strftime('%d %b')} – {lv.end_date.strftime('%d %b %Y')}"


# ---------------- Staff: request leave / absence ----------------

@leave_bp.route("/leave/my")
@login_required
@roles_required(*STAFF_ROLES)
def my_leave():
    staff = current_user.staff_profile
    if not staff:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    requests_ = (
        LeaveRequest.query.filter_by(staff_id=staff.id)
        .order_by(LeaveRequest.created_at.desc())
        .all()
    )
    today = local_today()
    return render_template(
        "leave/my_leave.html",
        requests=requests_, types=LeaveType.LABELS, today=today,
        earliest=(today - timedelta(days=BACKDATE_DAYS)).isoformat(),
        form=request.args,
    )


@leave_bp.route("/leave/request", methods=["POST"])
@login_required
@roles_required(*STAFF_ROLES)
def submit_request():
    staff = current_user.staff_profile
    if not staff:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    leave_type = request.form.get("leave_type")
    start = _parse_date(request.form.get("start_date"))
    end = _parse_date(request.form.get("end_date")) or start
    reason = request.form.get("reason", "").strip()

    def back(msg):
        flash(msg, "danger")
        return redirect(url_for("leave.my_leave", **{
            k: request.form.get(k, "") for k in ("leave_type", "start_date", "end_date", "reason")
        }))

    today = local_today()
    if leave_type not in LeaveType.LABELS:
        return back("Please choose a leave type.")
    if not start:
        return back("Please choose the date you'll be away from.")
    if end < start:
        return back("The end date can't be before the start date.")
    if start < today - timedelta(days=BACKDATE_DAYS):
        return back(f"Requests can only be back-dated up to {BACKDATE_DAYS} days. Please speak to the admin about older absences.")
    if (end - start).days + 1 > MAX_SPAN_DAYS:
        return back("That date range is too long — please split it up.")
    if not reason:
        return back("Please give a short reason so the admin can review your request.")

    clash = LeaveRequest.query.filter(
        LeaveRequest.staff_id == staff.id,
        LeaveRequest.status.in_([LeaveStatus.PENDING, LeaveStatus.APPROVED]),
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    ).first()
    if clash:
        return back(f"You already have a {clash.status} request covering {_fmt_range(clash)}.")

    lv = LeaveRequest(
        staff_id=staff.id, leave_type=leave_type, start_date=start, end_date=end,
        reason=reason, status=LeaveStatus.PENDING,
    )
    db.session.add(lv)
    db.session.flush()

    log_action(
        action="leave.requested",
        entity_type="LeaveRequest",
        entity_id=lv.id,
        after={"type": leave_type, "from": str(start), "to": str(end)},
        description=f"{current_user.full_name} requested {lv.type_label.lower()} for {_fmt_range(lv)}",
    )
    db.session.commit()

    flash("Request sent. You'll see it marked approved or rejected here once the admin has reviewed it.", "success")
    return redirect(url_for("leave.my_leave"))


@leave_bp.route("/leave/<int:leave_id>/cancel", methods=["POST"])
@login_required
@roles_required(*STAFF_ROLES)
def cancel_request(leave_id):
    lv = LeaveRequest.query.get_or_404(leave_id)
    staff = current_user.staff_profile
    if not staff or lv.staff_id != staff.id:
        abort(403)
    if lv.status != LeaveStatus.PENDING:
        flash("Only a request that's still pending can be withdrawn. Ask the admin if you need to change an approved one.", "warning")
        return redirect(url_for("leave.my_leave"))

    lv.status = LeaveStatus.CANCELLED
    log_action(
        action="leave.cancelled",
        entity_type="LeaveRequest",
        entity_id=lv.id,
        description=f"{current_user.full_name} withdrew their leave request for {_fmt_range(lv)}",
    )
    db.session.commit()
    flash("Request withdrawn.", "success")
    return redirect(url_for("leave.my_leave"))


# ---------------- Admin / Owner: review requests ----------------

@leave_bp.route("/leave/requests")
@login_required
@roles_required(*REVIEWER_ROLES)
@permission_required("leave.manage")
def review_requests():
    status = request.args.get("status", LeaveStatus.PENDING)
    query = LeaveRequest.query
    if status in LeaveStatus.ALL:
        query = query.filter_by(status=status)
    else:
        status = "all"

    requests_ = query.order_by(LeaveRequest.created_at.desc()).all()
    counts = {s: LeaveRequest.query.filter_by(status=s).count() for s in LeaveStatus.ALL}
    own_staff_id = current_user.staff_profile.id if current_user.staff_profile else None

    return render_template(
        "leave/requests.html",
        requests=requests_, status=status, counts=counts,
        today=local_today(), own_staff_id=own_staff_id,
    )


@leave_bp.route("/leave/<int:leave_id>/decide", methods=["POST"])
@login_required
@roles_required(*REVIEWER_ROLES)
@permission_required("leave.manage")
def decide(leave_id):
    lv = LeaveRequest.query.get_or_404(leave_id)
    decision = request.form.get("decision")
    note = request.form.get("admin_note", "").strip()[:255] or None
    name = lv.staff.user.full_name

    # Nobody approves their own leave — an admin's request goes to the
    # owner or another admin.
    if lv.staff.user_id == current_user.id:
        flash("You can't review your own request — it needs to be approved by someone else.", "danger")
        return redirect(url_for("leave.review_requests"))

    if decision in ("approve", "reject") and lv.status != LeaveStatus.PENDING:
        flash("That request has already been dealt with.", "warning")
        return redirect(url_for("leave.review_requests"))

    if decision == "approve":
        lv.status = LeaveStatus.APPROVED
        action, verb = "leave.approved", "approved"
    elif decision == "reject":
        lv.status = LeaveStatus.REJECTED
        action, verb = "leave.rejected", "rejected"
    elif decision == "revoke":
        if lv.status != LeaveStatus.APPROVED:
            flash("Only an approved request can be revoked.", "warning")
            return redirect(url_for("leave.review_requests", status=LeaveStatus.APPROVED))
        lv.status = LeaveStatus.CANCELLED
        action, verb = "leave.revoked", "revoked"
    else:
        abort(400)

    lv.decided_by_id = current_user.id
    lv.decided_at = datetime.utcnow()
    lv.admin_note = note

    log_action(
        action=action,
        entity_type="LeaveRequest",
        entity_id=lv.id,
        after={"status": lv.status, "note": note},
        description=f"{current_user.full_name} {verb} {name}'s {lv.type_label.lower()} for {_fmt_range(lv)}",
    )
    db.session.commit()

    flash(f"{name}'s request {verb}.", "success")

    if decision == "approve":
        clashes = DutyAssignment.query.filter(
            DutyAssignment.staff_id == lv.staff_id,
            DutyAssignment.start_date <= lv.end_date,
            DutyAssignment.end_date >= lv.start_date,
        ).all()
        if clashes:
            titles = ", ".join(sorted({a.duty.title for a in clashes}))
            flash(
                f"Heads up: {name} is assigned duty during these dates ({titles}). "
                "You may want to reassign it from the Duty Roster.",
                "warning",
            )

    return redirect(url_for("leave.review_requests", status=request.form.get("return_status", LeaveStatus.PENDING)))
