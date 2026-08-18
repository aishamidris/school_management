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

    staff = db.relationship("Staff")

    __table_args__ = (
        db.UniqueConstraint("staff_id", "date", name="uq_staff_attendance_per_day"),
    )
