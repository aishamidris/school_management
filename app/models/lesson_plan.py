from datetime import datetime, date as date_cls
from app.extensions import db


class LessonPlan(db.Model):
    """A single lesson plan, in the classic two-column-header /
    three-column-content-development / two-column-footer format."""

    __tablename__ = "lesson_plans"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("staff.id"), nullable=False)
    class_subject_id = db.Column(db.Integer, db.ForeignKey("class_subjects.id"), nullable=False)

    date = db.Column(db.Date, nullable=False, default=date_cls.today)
    topic = db.Column(db.String(200), nullable=False)
    sub_topic = db.Column(db.String(200))
    behavioral_objective = db.Column(db.Text)
    teaching_methods = db.Column(db.Text)
    teaching_aid = db.Column(db.Text)
    introduction = db.Column(db.Text)
    presentation = db.Column(db.Text)

    evaluation = db.Column(db.Text)
    summary = db.Column(db.Text)
    conclusion = db.Column(db.Text)
    reference = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teacher = db.relationship("Staff")
    class_subject = db.relationship("ClassSubject")
    days = db.relationship(
        "LessonPlanDay",
        backref="lesson_plan",
        order_by="LessonPlanDay.order_index",
        cascade="all, delete-orphan",
    )


class LessonPlanDay(db.Model):
    """One 'Day N' block inside the Content Development grid."""

    __tablename__ = "lesson_plan_days"

    id = db.Column(db.Integer, primary_key=True)
    lesson_plan_id = db.Column(db.Integer, db.ForeignKey("lesson_plans.id"), nullable=False)
    order_index = db.Column(db.Integer, nullable=False, default=0)

    steps = db.relationship(
        "LessonPlanStep",
        backref="day",
        order_by="LessonPlanStep.order_index",
        cascade="all, delete-orphan",
    )

    @property
    def label(self):
        return f"Day {self.order_index + 1}"


class LessonPlanStep(db.Model):
    """One step row within a day: Content Development / Teacher's
    Activity / Pupil's Activity."""

    __tablename__ = "lesson_plan_steps"

    id = db.Column(db.Integer, primary_key=True)
    day_id = db.Column(db.Integer, db.ForeignKey("lesson_plan_days.id"), nullable=False)
    order_index = db.Column(db.Integer, nullable=False, default=0)

    content_development = db.Column(db.Text)
    teacher_activity = db.Column(db.Text)
    pupil_activity = db.Column(db.Text)

    @property
    def label(self):
        return f"Step {self.order_index + 1}"
