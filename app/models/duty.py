from datetime import datetime
from app.extensions import db


class Duty(db.Model):
    """A kind of duty the owner defines — 'Morning Assembly', 'Gate Duty',
    'Dining Hall Supervision'. This is the template; who does it and when
    lives in DutyAssignment."""

    __tablename__ = "duties"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    location = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assignments = db.relationship("DutyAssignment", backref="duty", cascade="all, delete-orphan")


class DutyAssignment(db.Model):
    """One staff member doing one duty over a time frame: a date range
    (both ends inclusive — a single day is start == end) and an optional
    daily time window within it."""

    __tablename__ = "duty_assignments"

    id = db.Column(db.Integer, primary_key=True)
    duty_id = db.Column(db.Integer, db.ForeignKey("duties.id"), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False, index=True)

    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)

    notes = db.Column(db.String(255))

    assigned_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    staff = db.relationship("Staff", backref="duty_assignments")
    assigned_by = db.relationship("User", foreign_keys=[assigned_by_id])

    def state_on(self, today):
        """'current', 'upcoming' or 'past' relative to the given date."""
        if self.end_date < today:
            return "past"
        if self.start_date > today:
            return "upcoming"
        return "current"

    @property
    def time_window_label(self):
        if self.start_time and self.end_time:
            return f"{self.start_time.strftime('%H:%M')}–{self.end_time.strftime('%H:%M')}"
        if self.start_time:
            return f"from {self.start_time.strftime('%H:%M')}"
        if self.end_time:
            return f"until {self.end_time.strftime('%H:%M')}"
        return "All day"
