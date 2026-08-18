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
