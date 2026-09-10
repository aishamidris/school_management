from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role
from app.models.permission import Permission
from app.utils.decorators import roles_required
from app.utils.audit import log_action
from app.utils.permissions import PERMISSIONS, CONFIGURABLE_ROLES, STRUCTURALLY_RESTRICTED

permissions_bp = Blueprint("permissions", __name__, template_folder="../../templates/permissions")


@permissions_bp.route("/permissions", methods=["GET", "POST"])
@login_required
@roles_required(Role.OWNER)
def manage():
    if request.method == "POST":
        changed = []
        for role in CONFIGURABLE_ROLES:
            for key in PERMISSIONS:
                if (role, key) in STRUCTURALLY_RESTRICTED:
                    continue  # disabled in the UI on purpose — never touched by a save

                field_name = f"{role}::{key}"
                should_allow = field_name in request.form

                row = Permission.query.filter_by(role=role, capability=key).first()
                if not row:
                    row = Permission(role=role, capability=key, allowed=should_allow)
                    db.session.add(row)
                    if should_allow:
                        changed.append(f"{role}:{key}")
                elif row.allowed != should_allow:
                    row.allowed = should_allow
                    changed.append(f"{role}:{key}={'on' if should_allow else 'off'}")

        log_action(
            action="permissions.updated",
            entity_type="Permission",
            after={"changed": changed},
            description=f"{current_user.full_name} updated role permissions ({len(changed)} change(s))",
        )
        db.session.commit()

        flash("Permissions updated.", "success")
        return redirect(url_for("permissions.manage"))

    # Build a lookup: {(role, key): allowed}
    rows = Permission.query.filter(Permission.role.in_(CONFIGURABLE_ROLES)).all()
    grants = {(r.role, r.capability): r.allowed for r in rows}

    # Group capabilities by module for display
    grouped = {}
    for key, (label, module) in PERMISSIONS.items():
        grouped.setdefault(module, []).append((key, label))

    return render_template(
        "permissions/manage.html",
        grouped=grouped,
        grants=grants,
        roles=CONFIGURABLE_ROLES,
        restricted=STRUCTURALLY_RESTRICTED,
    )


@permissions_bp.route("/permissions/reset/<role>", methods=["POST"])
@login_required
@roles_required(Role.OWNER)
def reset_role(role):
    from app.utils.permissions import DEFAULT_PERMISSIONS

    if role not in CONFIGURABLE_ROLES:
        flash("Invalid role.", "danger")
        return redirect(url_for("permissions.manage"))

    defaults = DEFAULT_PERMISSIONS.get(role, set())
    for key in PERMISSIONS:
        if (role, key) in STRUCTURALLY_RESTRICTED:
            continue
        row = Permission.query.filter_by(role=role, capability=key).first()
        allowed = key in defaults
        if row:
            row.allowed = allowed
        else:
            db.session.add(Permission(role=role, capability=key, allowed=allowed))

    log_action(
        action="permissions.reset",
        entity_type="Permission",
        after={"role": role},
        description=f"{current_user.full_name} reset {role} permissions to defaults",
    )
    db.session.commit()

    flash(f"{role.capitalize()} permissions reset to defaults.", "success")
    return redirect(url_for("permissions.manage"))
