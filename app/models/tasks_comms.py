from datetime import datetime
from app.extensions import db


class TaskStatus:
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    COMPLETED = "completed"


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)

    assigned_to_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    deadline = db.Column(db.Date)
    status = db.Column(db.String(20), default=TaskStatus.NOT_STARTED)
    progress_percent = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    assigned_to = db.relationship("Staff")


class AnnouncementAudience:
    EVERYONE = "everyone"
    STAFF = "staff"
    PARENTS = "parents"
    STUDENTS = "students"
    SPECIFIC_CLASS = "specific_class"
    SPECIFIC_STAFF = "specific_staff"


class Announcement(db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)

    audience = db.Column(db.String(20), default=AnnouncementAudience.EVERYONE)
    class_arm_id = db.Column(db.Integer, db.ForeignKey("class_arms.id"), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
