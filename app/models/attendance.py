from datetime import datetime
from app.extensions import db


class AttendanceStatus:
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


class StudentAttendance(db.Model):
    __tablename__ = "student_attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    class_arm_id = db.Column(db.Integer, db.ForeignKey("class_arms.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), default=AttendanceStatus.PRESENT)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student")

    __table_args__ = (
        db.UniqueConstraint("student_id", "date", name="uq_student_attendance_per_day"),
    )


class StaffAttendance(db.Model):
    __tablename__ = "staff_attendance"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), default=AttendanceStatus.PRESENT)
    check_in = db.Column(db.DateTime)
    check_out = db.Column(db.DateTime)

    # Decided once, at check-in, against the cut-off in force at that
    # moment, and then stored — so changing the cut-off later never
    # rewrites history.
    is_late = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    minutes_late = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    # Location captured from the staff member's browser at the moment of
    # check-in/out, used to verify they were actually on campus. verified
    # is None when there's nothing to judge (no school location configured
    # yet, or the browser didn't provide coordinates), True when within
    # the configured radius, False when outside it.
    check_in_lat = db.Column(db.Float)
    check_in_lng = db.Column(db.Float)
    check_in_accuracy_m = db.Column(db.Float)
    check_in_distance_m = db.Column(db.Float)
    check_in_verified = db.Column(db.Boolean)

    check_out_lat = db.Column(db.Float)
    check_out_lng = db.Column(db.Float)
    check_out_accuracy_m = db.Column(db.Float)
    check_out_distance_m = db.Column(db.Float)
    check_out_verified = db.Column(db.Boolean)

    staff = db.relationship("Staff")

    __table_args__ = (
        db.UniqueConstraint("staff_id", "date", name="uq_staff_attendance_per_day"),
    )
