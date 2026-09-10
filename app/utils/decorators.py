from functools import wraps
from flask import abort
from flask_login import current_user


def roles_required(*allowed_roles):
    """Restrict a route to specific roles.

    Usage:
        @roles_required(Role.OWNER, Role.ADMIN)
        def some_view():
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in allowed_roles:
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(key):
    """Restrict a route to users who hold a specific granted permission
    (see app/utils/permissions.py). Owner always passes. Use this for
    fine-grained capability gates within a role — pair with
    roles_required first if you also need a hard structural boundary
    (e.g. accountants can never reach reconciliation, full stop).

    Usage:
        @roles_required(Role.OWNER, Role.ADMIN, Role.ACCOUNTANT)
        @permission_required('payments.record')
        def record_payment():
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            from app.utils.permissions import has_permission
            if not current_user.is_authenticated:
                abort(401)
            if not has_permission(current_user, key):
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped
    return decorator
