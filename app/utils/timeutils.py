"""Local-time helpers.

Timestamps are stored in the database as naive UTC (datetime.utcnow()),
but "late" is a wall-clock idea — 08:00 means 08:00 at the school, not
08:00 UTC. These helpers convert using the timezone saved in
SchoolSettings (default Africa/Lagos) so the late cut-off, the recorded
attendance date, and the times shown on screen all agree.
"""
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

DEFAULT_TZ = "Africa/Lagos"


def is_valid_timezone(name):
    if not name or ZoneInfo is None:
        return False
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def _resolve(name):
    name = name or DEFAULT_TZ
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def get_tz(name=None):
    """Timezone object for the school. Falls back to UTC if the name
    can't be resolved (e.g. the tzdata package isn't installed on
    Windows) rather than crashing check-in.

    When no name is passed the saved school timezone is looked up once
    per request and cached on flask.g, because templates call this for
    every time they print.
    """
    if name is not None:
        return _resolve(name)

    from flask import g, has_request_context
    in_request = has_request_context()
    if in_request and hasattr(g, "_school_tz"):
        return g._school_tz

    from app.models.settings import SchoolSettings
    tz = _resolve(SchoolSettings.get().timezone)
    if in_request:
        g._school_tz = tz
    return tz


def to_local(dt_utc, tz=None):
    """Naive-UTC datetime -> aware local datetime (None passes through)."""
    if dt_utc is None:
        return None
    tz = tz or get_tz()
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)


def local_now(tz=None):
    return datetime.now(tz or get_tz())


def local_today(tz=None):
    return local_now(tz).date()


def format_local(dt_utc, fmt="%H:%M", empty="—"):
    """Jinja-friendly: naive-UTC datetime -> formatted school-local time."""
    if not dt_utc:
        return empty
    return to_local(dt_utc).strftime(fmt)
