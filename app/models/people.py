from datetime import datetime
from app.extensions import db


class StudentStatus:
    ACTIVE = "active"
    GRADUATED = "graduated"
    WITHDRAWN = "withdrawn"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=True)

    admission_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    photo_path = db.Column(db.String(255))
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))

    class_arm_id = db.Column(db.Integer, db.ForeignKey("class_arms.id"), nullable=True)
    admission_date = db.Column(db.Date, default=datetime.utcnow)
    previous_school = db.Column(db.String(120))

    address = db.Column(db.String(255))
    medical_info = db.Column(db.Text)

    status = db.Column(db.String(20), default=StudentStatus.ACTIVE, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    guardians = db.relationship("StudentGuardian", backref="student", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Student {self.admission_number} {self.full_name}>"


class ParentProfile(db.Model):
    """Profile data for a parent/guardian user."""
    __tablename__ = "parent_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    occupation = db.Column(db.String(120))
    address = db.Column(db.String(255))

    children = db.relationship("StudentGuardian", backref="parent", cascade="all, delete-orphan")


class StudentGuardian(db.Model):
    """Many-to-many link: a student can have multiple guardians,
    a guardian can have multiple children."""
    __tablename__ = "student_guardians"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    parent_profile_id = db.Column(db.Integer, db.ForeignKey("parent_profiles.id"), nullable=False)
    relationship_type = db.Column(db.String(30))  # "Father", "Mother", "Guardian"
    is_primary_contact = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.UniqueConstraint("student_id", "parent_profile_id", name="uq_student_guardian"),
    )


class Staff(db.Model):
    """Profile data for owner/admin/accountant/teacher — anyone employed
    by the school. Their login role lives on User.role; this table holds
    the HR-ish details."""
    __tablename__ = "staff"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)

    staff_id_number = db.Column(db.String(30), unique=True)
    designation = db.Column(db.String(80))  # "Mathematics Teacher", "Head Accountant"
    date_employed = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Staff {self.staff_id_number}>"
