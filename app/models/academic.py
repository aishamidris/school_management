from app.extensions import db


class AcademicSession(db.Model):
    """e.g. '2026/2027'"""
    __tablename__ = "academic_sessions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), unique=True, nullable=False)  # "2026/2027"
    is_current = db.Column(db.Boolean, default=False)

    terms = db.relationship("Term", backref="session", cascade="all, delete-orphan")


class Term(db.Model):
    """e.g. First Term, Second Term, Third Term — belongs to a session."""
    __tablename__ = "terms"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False)
    name = db.Column(db.String(30), nullable=False)  # "First Term"
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_current = db.Column(db.Boolean, default=False)

    # Financial locking: once closed, payments/invoices for this term
    # cannot be edited directly — only via a correction request/approval flow.
    is_closed = db.Column(db.Boolean, default=False)

    __table_args__ = (db.UniqueConstraint("session_id", "name", name="uq_term_per_session"),)


class SchoolClass(db.Model):
    """e.g. JSS 1, JSS 2, SS 3 — the grade level."""
    __tablename__ = "school_classes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)  # "JSS 2"
    order = db.Column(db.Integer, default=0)  # for sorting / promotion sequence

    arms = db.relationship("ClassArm", backref="school_class", cascade="all, delete-orphan")


class ClassArm(db.Model):
    """e.g. JSS 2A, JSS 2B — a specific section within a class, tied to a session."""
    __tablename__ = "class_arms"

    id = db.Column(db.Integer, primary_key=True)
    school_class_id = db.Column(db.Integer, db.ForeignKey("school_classes.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("academic_sessions.id"), nullable=False)
    name = db.Column(db.String(10), nullable=False)  # "A", "B"

    class_teacher_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)

    students = db.relationship("Student", backref="class_arm")

    __table_args__ = (
        db.UniqueConstraint("school_class_id", "session_id", "name", name="uq_arm"),
    )

    @property
    def display_name(self):
        return f"{self.school_class.name}{self.name}"


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    code = db.Column(db.String(10))


class ClassSubject(db.Model):
    """Links a subject to a class arm and the teacher assigned to teach it."""
    __tablename__ = "class_subjects"

    id = db.Column(db.Integer, primary_key=True)
    class_arm_id = db.Column(db.Integer, db.ForeignKey("class_arms.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=True)

    class_arm = db.relationship("ClassArm", backref="class_subjects")
    subject = db.relationship("Subject")
    teacher = db.relationship("Staff")

    __table_args__ = (
        db.UniqueConstraint("class_arm_id", "subject_id", name="uq_class_subject"),
    )
