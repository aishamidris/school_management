import json
from flask_login import current_user
from app.extensions import db
from app.models.user import AuditLog


def log_action(action, entity_type, entity_id=None, before=None, after=None, description=None):
    """Write one audit log entry. Call this right after any create/edit/
    delete of something that matters (payments, students, results, etc).

    Example:
        log_action(
            action="payment.recorded",
            entity_type="Payment",
            entity_id=payment.id,
            after={"amount": str(payment.amount), "student": student.full_name},
            description=f"Recorded payment of NGN{payment.amount} for {student.full_name}",
        )
    """
    actor = current_user if current_user and current_user.is_authenticated else None

    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else "System",
        actor_role=actor.role if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_value=json.dumps(before, default=str) if before is not None else None,
        after_value=json.dumps(after, default=str) if after is not None else None,
        description=description,
    )
    db.session.add(entry)
    # Deliberately not committing here — caller commits as part of their
    # own transaction so the audit entry and the actual change succeed
    # or fail together.
    return entry
