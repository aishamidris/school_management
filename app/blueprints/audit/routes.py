import json
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request
from flask_login import login_required

from app.models.user import Role, AuditLog
from app.utils.decorators import roles_required, permission_required

audit_bp = Blueprint("audit", __name__, template_folder="../../templates/audit")

PER_PAGE = 30

# Deliberately owner/admin only, same class of restriction as reconciliation —
# the audit log is what lets the owner verify everyone else's work, so it
# can't itself be granted to the people it's watching.
OVERSIGHT_ROLES = (Role.OWNER, Role.ADMIN)


@audit_bp.route("/audit")
@login_required
@roles_required(*OVERSIGHT_ROLES)
@permission_required("audit.view")
def list_logs():
    query = AuditLog.query

    action_filter = request.args.get("action", "").strip()
    entity_filter = request.args.get("entity_type", "").strip()
    entity_id_filter = request.args.get("entity_id", type=int)
    role_filter = request.args.get("actor_role", "").strip()
    search = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    page = request.args.get("page", 1, type=int)

    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    if entity_filter:
        query = query.filter(AuditLog.entity_type == entity_filter)
    if entity_id_filter:
        query = query.filter(AuditLog.entity_id == entity_id_filter)
    if role_filter:
        query = query.filter(AuditLog.actor_role == role_filter)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (AuditLog.description.ilike(like)) | (AuditLog.actor_name.ilike(like))
        )
    if date_from:
        try:
            query = query.filter(AuditLog.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(AuditLog.created_at < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass

    query = query.order_by(AuditLog.created_at.desc())

    total = query.count()
    logs = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    all_actions = [
        r[0] for r in AuditLog.query.with_entities(AuditLog.action).distinct().order_by(AuditLog.action).all()
    ]
    all_entity_types = [
        r[0] for r in AuditLog.query.with_entities(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all()
    ]

    return render_template(
        "audit/list.html",
        logs=logs, page=page, total_pages=total_pages, total=total,
        all_actions=all_actions, all_entity_types=all_entity_types,
        action_filter=action_filter, entity_filter=entity_filter, entity_id_filter=entity_id_filter,
        role_filter=role_filter, search=search, date_from=date_from, date_to=date_to,
        roles=[Role.OWNER, Role.ADMIN, Role.ACCOUNTANT, Role.TEACHER, Role.PARENT, Role.STUDENT],
    )


@audit_bp.route("/audit/<int:log_id>")
@login_required
@roles_required(*OVERSIGHT_ROLES)
@permission_required("audit.view")
def view_log(log_id):
    log = AuditLog.query.get_or_404(log_id)

    def _pretty(raw):
        if not raw:
            return None
        try:
            return json.dumps(json.loads(raw), indent=2, sort_keys=True)
        except (ValueError, TypeError):
            return raw

    return render_template(
        "audit/detail.html", log=log, before=_pretty(log.before_value), after=_pretty(log.after_value)
    )
