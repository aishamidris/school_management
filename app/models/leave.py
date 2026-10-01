from datetime import datetime
from app.extensions import db


class LeaveType:
    ANNUAL = "annual"
    SICK = "sick"
    CASUAL = "casual"
    MATERNITY = "maternity"
    STUDY = "study"
    EMERGENCY = "emergency"
    OTHER = "other"

    LABELS = {
        ANNUAL: "Annual leave",
        SICK: "Sick leave",
        CASUAL: "Casual / personal",
        MATERNITY: "Maternity / paternity",
        STUDY: "Study / exam leave",
        EMERGENCY: "Emergency absence",
        OTHER: "Other",
    }


class LeaveStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    ALL = [PENDING, APPROVED, REJECTED, CANCELLED]


class LeaveRequest(db.Model):
    """A staff member's request to be on leave or absent for a date range
    (both ends inclusive). Once approved, the attendance views overlay it
    on every school day in the range where the person didn't check in, so
    the dashboard shows 'On leave' instead of 'Absent'. Nothing is written
    into staff_attendance for it — that table stays a record of what
    actually happened at the gate."""

    __tablename__ = "leave_requests"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False, index=True)

    leave_type = db.Column(db.String(20), nullable=False, default=LeaveType.CASUAL)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)

    status = db.Column(db.String(12), nullable=False, default=LeaveStatus.PENDING, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    admin_note = db.Column(db.String(255))

    staff = db.relationship("Staff", backref="leave_requests")
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])

    @property
    def type_label(self):
        return LeaveType.LABELS.get(self.leave_type, self.leave_type.title())

    @property
    def total_days(self):
        """Calendar days spanned (not school days — the attendance views
        work out which of these were actually school days)."""
        return (self.end_date - self.start_date).days + 1

    def covers(self, day):
        return self.start_date <= day <= self.end_date
