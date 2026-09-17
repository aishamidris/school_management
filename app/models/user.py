from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class Role:
    """Fixed role names used throughout the app.
    Kept as constants (not a DB table) so permission checks in code
    stay simple. If you outgrow this later, move to a Role/Permission
    table with a many-to-many join.
    """
    OWNER = "owner"
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    TEACHER = "teacher"
    PARENT = "parent"
    STUDENT = "student"

    ALL = [OWNER, ADMIN, ACCOUNTANT, TEACHER, PARENT, STUDENT]
    STAFF_ROLES = [OWNER, ADMIN, ACCOUNTANT, TEACHER]


class User(UserMixin, db.Model):
    """Every human who can log in — owner, admin, accountant, teacher,
    parent, or student — is a User. Role-specific data (e.g. Teacher's
    assigned subjects, Student's class) lives in linked profile tables.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False, index=True)

    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, index=True)
    phone = db.Column(db.String(30), unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime)
    failed_login_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # One-to-one links to role-specific profiles (nullable — a user has
    # at most one of these populated depending on their role)
    staff_profile = db.relationship("Staff", backref="user", uselist=False)
    parent_profile = db.relationship("ParentProfile", backref="user", uselist=False)
    student_profile = db.relationship("Student", backref="user", uselist=False)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def is_locked(self):
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    @property
    def profile_photo_path(self):
        """Wherever this user's uploaded photo lives, regardless of role
        (Staff and Student each keep their own photo_path column)."""
        if self.staff_profile and self.staff_profile.photo_path:
            return self.staff_profile.photo_path
        if self.student_profile and self.student_profile.photo_path:
            return self.student_profile.photo_path
        return None

    def __repr__(self):
        return f"<User {self.full_name} ({self.role})>"


class AuditLog(db.Model):
    """Every significant create/edit/delete action, anywhere in the app,
    should write one of these. This is what makes the owner<->accountant
    reconciliation feature meaningful — without it you can only see
    THAT numbers differ, not WHY.
    """
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    actor_name = db.Column(db.String(120))  # denormalized snapshot, survives user deletion
    actor_role = db.Column(db.String(20))

    action = db.Column(db.String(50), nullable=False)  # e.g. "payment.recorded", "payment.edited"
    entity_type = db.Column(db.String(50), nullable=False)  # e.g. "Payment", "Student"
    entity_id = db.Column(db.Integer)

    before_value = db.Column(db.Text)  # JSON snapshot before change
    after_value = db.Column(db.Text)   # JSON snapshot after change
    description = db.Column(db.String(255))  # human-readable summary

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship("User")

    def __repr__(self):
        return f"<AuditLog {self.action} by {self.actor_name} @ {self.created_at}>"
