"""Staff punctuality & attendance maths.

The calculation itself (compute_term_summary and evaluate_lateness) is
pure Python — it takes plain objects and dates and never touches the
database — so it can be unit-tested on its own. The load_* helpers at
the bottom are the thin database layer that feeds it.

How a term is counted
---------------------
* A **school day** is a date inside the term window on which at least one
  staff member checked in. Using real check-ins means weekends, public
  holidays and closures never count against anyone, without needing a
  school calendar to be maintained.
* For each staff member, every school day lands in exactly one bucket:
    present  - they checked in on time
    late     - they checked in after the cut-off in force that day
    leave    - no check-in, but covered by an approved leave request
    absent   - no check-in and no approved leave
    not_in_yet - today only, no check-in yet (not counted as absent
                 until the day is over)
    na       - before the staff member's employment date
* Punctuality % = on-time check-ins / days present. Attendance % =
  days present / (days present + absent); leave days are excluded from
  that denominator because approved leave isn't a failure to attend.
* Ranking: highest punctuality first, then fewer total minutes late, then
  more days present. Only staff who were present for at least half of the
  school days that applied to them are ranked, so someone who turned up
  once doesn't top a "most punctual" list.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MIN_ATTENDANCE_RATE_FOR_RANKING = 0.5


# ---------------------------------------------------------------- lateness

def evaluate_lateness(check_in_utc, cutoff_time, tz):
    """Decide whether a check-in is late.

    check_in_utc : naive UTC datetime (how timestamps are stored)
    cutoff_time  : datetime.time at the school in `tz`, or None (not tracked)
    tz           : tzinfo for the school

    Compared to the minute: 08:00:59 is still on time for an 08:00
    cut-off, 08:01:00 is one minute late. Returns (is_late, minutes_late).
    """
    if cutoff_time is None or check_in_utc is None:
        return False, 0

    from datetime import timezone
    local = check_in_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    local_minute = local.replace(second=0, microsecond=0)
    cutoff = datetime.combine(local.date(), cutoff_time).replace(tzinfo=local.tzinfo)

    if local_minute > cutoff:
        return True, int((local_minute - cutoff).total_seconds() // 60)
    return False, 0


# ------------------------------------------------------------ term summary

@dataclass
class DayEntry:
    date: object
    state: str            # present | late | leave | absent | not_in_yet | na
    record: object = None
    leave: object = None


@dataclass
class StaffTermStats:
    staff: object
    entries: list = field(default_factory=list)
    days_present: int = 0
    on_time: int = 0
    late: int = 0
    leave_days: int = 0
    absent: int = 0
    total_minutes_late: int = 0
    punctuality_rate: float = None   # 0-100, None when never present
    attendance_rate: float = None    # 0-100, None when no expected days
    rank: int = None

    @property
    def avg_minutes_late(self):
        return round(self.total_minutes_late / self.late) if self.late else 0


@dataclass
class TermSummary:
    start: object
    end: object
    school_days: list
    rows: list

    @property
    def ranked(self):
        return [r for r in self.rows if r.rank is not None]

    def row_for(self, staff_id):
        for r in self.rows:
            if r.staff.id == staff_id:
                return r
        return None


def find_leave(leaves, day):
    for lv in leaves:
        if lv.start_date <= day <= lv.end_date:
            return lv
    return None


def compute_term_summary(staff_list, records, approved_leaves, start, end, today):
    """staff_list      : Staff-like objects (id, date_employed, user.full_name)
    records         : StaffAttendance-like rows for ALL staff in the window
                      (all staff are needed to know which days were school days)
    approved_leaves : approved LeaveRequest-like rows (staff_id, start_date, end_date)
    start, end      : inclusive window; end is already capped at today
    """
    in_window = [r for r in records if start <= r.date <= end and r.check_in is not None]
    school_days = sorted({r.date for r in in_window})

    by_staff = {}
    for r in in_window:
        by_staff.setdefault(r.staff_id, {})[r.date] = r

    leaves_by_staff = {}
    for lv in approved_leaves:
        leaves_by_staff.setdefault(lv.staff_id, []).append(lv)

    rows = []
    for staff in staff_list:
        own = by_staff.get(staff.id, {})
        own_leaves = leaves_by_staff.get(staff.id, [])
        stats = StaffTermStats(staff=staff)

        for day in school_days:
            rec = own.get(day)
            if rec is not None:
                if rec.is_late:
                    stats.late += 1
                    stats.total_minutes_late += rec.minutes_late or 0
                    stats.entries.append(DayEntry(day, "late", record=rec))
                else:
                    stats.on_time += 1
                    stats.entries.append(DayEntry(day, "present", record=rec))
                continue

            employed = getattr(staff, "date_employed", None)
            if employed and day < employed:
                stats.entries.append(DayEntry(day, "na"))
                continue

            lv = find_leave(own_leaves, day)
            if lv is not None:
                stats.leave_days += 1
                stats.entries.append(DayEntry(day, "leave", leave=lv))
            elif day == today:
                stats.entries.append(DayEntry(day, "not_in_yet"))
            else:
                stats.absent += 1
                stats.entries.append(DayEntry(day, "absent"))

        stats.days_present = stats.on_time + stats.late
        if stats.days_present:
            stats.punctuality_rate = round(stats.on_time / stats.days_present * 100, 1)
        expected = stats.days_present + stats.absent
        if expected:
            stats.attendance_rate = round(stats.days_present / expected * 100, 1)
        rows.append(stats)

    _assign_ranks(rows)
    rows.sort(key=_display_order)
    return TermSummary(start=start, end=end, school_days=school_days, rows=rows)


def _rank_key(s):
    return (-round(s.punctuality_rate, 4), s.total_minutes_late)


def _name(s):
    return (s.staff.user.full_name or "").lower()


def _assign_ranks(rows):
    eligible = [
        s for s in rows
        if s.days_present
        and s.attendance_rate is not None
        and s.attendance_rate / 100 >= MIN_ATTENDANCE_RATE_FOR_RANKING
    ]
    eligible.sort(key=lambda s: (_rank_key(s), -s.days_present, _name(s)))
    previous_key, previous_rank = None, 0
    for position, s in enumerate(eligible, start=1):
        key = _rank_key(s)
        s.rank = previous_rank if key == previous_key else position
        previous_key, previous_rank = key, s.rank


def _display_order(s):
    # ranked staff first, in rank order; everyone else after, alphabetically
    if s.rank is not None:
        return (0, s.rank, -s.days_present, _name(s))
    return (1, 0, 0, _name(s))


# ----------------------------------------------------------- term window

def term_window(term, today):
    """(start, end) inclusive, with end capped at today. None when the term
    has no start date yet (the owner needs to set it under Sessions &
    Terms). If the term hasn't started, end < start and the summary is
    simply empty."""
    if term is None or term.start_date is None:
        return None
    end = min(term.end_date, today) if term.end_date else today
    return term.start_date, end


# ------------------------------------------------------- database layer

def load_term_summary(term, today, extra_staff=None):
    """Summary for every active staff member (plus `extra_staff`, e.g. a
    deactivated person whose history an admin is looking at). Returns None
    if the term has no start date."""
    from app.models.people import Staff
    from app.models.attendance import StaffAttendance
    from app.models.leave import LeaveRequest, LeaveStatus

    window = term_window(term, today)
    if window is None:
        return None
    start, end = window

    staff_list = Staff.query.filter_by(is_active=True).all()
    if extra_staff is not None and all(s.id != extra_staff.id for s in staff_list):
        staff_list.append(extra_staff)

    records = StaffAttendance.query.filter(
        StaffAttendance.date >= start, StaffAttendance.date <= end
    ).all()

    leaves = LeaveRequest.query.filter(
        LeaveRequest.status == LeaveStatus.APPROVED,
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    ).all()

    return compute_term_summary(staff_list, records, leaves, start, end, today)


def approved_leave_map(day):
    """{staff_id: LeaveRequest} for approved leave covering `day`."""
    from app.models.leave import LeaveRequest, LeaveStatus
    rows = LeaveRequest.query.filter(
        LeaveRequest.status == LeaveStatus.APPROVED,
        LeaveRequest.start_date <= day,
        LeaveRequest.end_date >= day,
    ).all()
    return {lv.staff_id: lv for lv in rows}


def current_term():
    from app.models.academic import AcademicSession, Term
    session = AcademicSession.query.filter_by(is_current=True).first()
    if not session:
        return None
    return Term.query.filter_by(session_id=session.id, is_current=True).first()
