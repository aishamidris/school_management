from datetime import datetime
from app.extensions import db


class QuestionType:
    MCQ = "mcq"
    THEORY = "theory"


class AssessmentType:
    CA = "ca"
    ASSIGNMENT = "assignment"
    MID_TERM = "mid_term"
    FINAL = "final"
    PRACTICAL = "practical"
    PROJECT = "project"


class Exam(db.Model):
    """A single assessment instance, e.g. 'JSS2 Mathematics Final Exam - First Term'."""
    __tablename__ = "exams"

    id = db.Column(db.Integer, primary_key=True)
    class_subject_id = db.Column(db.Integer, db.ForeignKey("class_subjects.id"), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    assessment_type = db.Column(db.String(20), default=AssessmentType.FINAL)
    total_marks = db.Column(db.Numeric(6, 2), default=100)
    duration_minutes = db.Column(db.Integer)  # for online exams
    is_online = db.Column(db.Boolean, default=False)
    question_deadline = db.Column(db.Date, nullable=True)  # set by owner/admin — when questions are due

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    class_subject = db.relationship("ClassSubject")
    term = db.relationship("Term")
    questions = db.relationship("Question", backref="exam", cascade="all, delete-orphan")


class Question(db.Model):
    """A single question, created manually or via the paste-import parser.
    For MCQ: options + correct_option_id are used. For theory:
    marking_guide is used and it's marked manually."""
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=True)  # null = lives only in question bank
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True)  # for bank tagging
    school_class_id = db.Column(db.Integer, db.ForeignKey("school_classes.id"), nullable=True)  # for bank tagging
    topic = db.Column(db.String(80))  # e.g. "Algebra" — for question bank organization
    section = db.Column(db.String(80))  # e.g. "Section A - Objectives" — groups within one exam

    question_type = db.Column(db.String(10), default=QuestionType.MCQ)
    prompt = db.Column(db.Text, nullable=False)
    marks = db.Column(db.Numeric(6, 2), default=1)
    marking_guide = db.Column(db.Text)  # theory questions: expected answer / rubric

    options = db.relationship("QuestionOption", backref="question", cascade="all, delete-orphan")


class QuestionOption(db.Model):
    __tablename__ = "question_options"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    label = db.Column(db.String(5))  # "A", "B", "C", "D"
    text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)


class Result(db.Model):
    """A student's aggregated score for a subject in a term —
    CA + Exam = Total, with grade computed from the school's
    configurable grading scale."""
    __tablename__ = "results"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    class_subject_id = db.Column(db.Integer, db.ForeignKey("class_subjects.id"), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id"), nullable=False)

    ca_score = db.Column(db.Numeric(6, 2), default=0)
    exam_score = db.Column(db.Numeric(6, 2), default=0)
    total_score = db.Column(db.Numeric(6, 2), default=0)
    grade = db.Column(db.String(5))

    entered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    entered_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student")
    class_subject = db.relationship("ClassSubject")

    __table_args__ = (
        db.UniqueConstraint("student_id", "class_subject_id", "term_id", name="uq_result"),
    )


class GradeBand(db.Model):
    """Configurable grading scale, e.g. 70-100 = A. Editable by admin
    instead of hard-coded in application logic."""
    __tablename__ = "grade_bands"

    id = db.Column(db.Integer, primary_key=True)
    min_score = db.Column(db.Numeric(6, 2), nullable=False)
    max_score = db.Column(db.Numeric(6, 2), nullable=False)
    grade = db.Column(db.String(5), nullable=False)
    remark = db.Column(db.String(40))  # "Excellent", "Good", "Fail"
