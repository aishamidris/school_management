from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from app.models.user import Role
from app.models.people import Student, Staff
from app.models.academic import AcademicSession, Term
from app.models.finance import Invoice
from app.models.exam import Result, Exam
from app.models.tasks_comms import Task, TaskStatus
from app.utils.permissions import has_permission

main_bp = Blueprint("main", __name__, template_folder="../../templates/dashboard")


def _current_term():
    session = AcademicSession.query.filter_by(is_current=True).first()
    if not session:
        return None
    return Term.query.filter_by(session_id=session.id, is_current=True).first()


@main_bp.route("/")
@login_required
def dashboard():
    if current_user.role == Role.OWNER:
        return owner_admin_dashboard()
    elif current_user.role == Role.ADMIN:
        if has_permission(current_user, "dashboard.owner_view"):
            return owner_admin_dashboard()
        return admin_limited_dashboard()
    elif current_user.role == Role.ACCOUNTANT:
        return accountant_dashboard()
    elif current_user.role == Role.TEACHER:
        return teacher_dashboard()
    elif current_user.role == Role.PARENT:
        return parent_dashboard()
    elif current_user.role == Role.STUDENT:
        return student_dashboard()
    return render_template("dashboard/generic.html")


def admin_limited_dashboard():
    """Shown to admins who don't have the dashboard.owner_view permission —
    a plain welcome + shortcuts to whatever they *do* have access to,
    instead of the owner's financial figures."""
    return render_template("dashboard/admin_limited.html")


def owner_admin_dashboard():
    total_students = Student.query.filter_by(status="active").count()
    total_staff = Staff.query.filter_by(is_active=True).count()

    invoices = Invoice.query.all()
    expected = sum(inv.net_expected for inv in invoices) or 0
    collected = sum(inv.total_paid for inv in invoices) or 0
    outstanding = expected - collected

    pending_tasks = Task.query.filter(Task.status != TaskStatus.COMPLETED).count()

    stats = {
        "total_students": total_students,
        "total_staff": total_staff,
        "expected_fees": expected,
        "collected_fees": collected,
        "outstanding_fees": outstanding,
        "collection_rate": round((collected / expected * 100), 1) if expected else 0,
        "pending_tasks": pending_tasks,
    }
    return render_template("dashboard/owner_admin.html", stats=stats)


def accountant_dashboard():
    from datetime import date
    from app.models.finance import Payment

    term = _current_term()
    today_payments = []
    today_total = 0
    outstanding_total = 0
    invoice_count = 0

    if term:
        invoices = Invoice.query.filter_by(term_id=term.id).all()
        outstanding_total = sum((inv.outstanding for inv in invoices), start=0)
        invoice_count = len(invoices)

        today_payments = (
            Payment.query.join(Invoice)
            .filter(Invoice.term_id == term.id, Payment.recorded_by_id == current_user.id,
                    Payment.is_voided.is_(False), func.date(Payment.recorded_at) == date.today())
            .all()
        )
        today_total = sum((p.amount for p in today_payments), start=0)

    return render_template(
        "dashboard/accountant.html",
        term=term, today_count=len(today_payments), today_total=today_total,
        outstanding_total=outstanding_total, invoice_count=invoice_count,
    )


def teacher_dashboard():
    if not current_user.staff_profile:
        return render_template(
            "dashboard/teacher.html", class_subjects=[], class_teacher_of=[],
            total_students=0, exams_due=[], term=None,
        )

    from datetime import date
    from app.models.academic import ClassSubject, ClassArm

    class_subjects = ClassSubject.query.filter_by(teacher_id=current_user.staff_profile.id).all()
    class_arm_ids = {cs.class_arm_id for cs in class_subjects}

    current_session = AcademicSession.query.filter_by(is_current=True).first()
    class_teacher_of = []
    if current_session:
        class_teacher_of = (
            ClassArm.query.filter_by(
                class_teacher_id=current_user.staff_profile.id, session_id=current_session.id
            ).all()
        )

    total_students = (
        Student.query.filter(Student.class_arm_id.in_(class_arm_ids), Student.status == "active").count()
        if class_arm_ids else 0
    )

    exams_due = []
    if class_subjects:
        exams = Exam.query.filter(
            Exam.class_subject_id.in_([cs.id for cs in class_subjects]),
            Exam.question_deadline.isnot(None),
        ).order_by(Exam.question_deadline).all()
        exams_due = exams[:5]

    term = _current_term()

    return render_template(
        "dashboard/teacher.html",
        class_subjects=class_subjects,
        class_teacher_of=class_teacher_of,
        total_students=total_students,
        exams_due=exams_due,
        term=term,
        today=date.today(),
    )


def _student_summary(student, term):
    """Shared snapshot used by both the parent's child-card and the
    student's own dashboard — one child's fees + results for a term."""
    invoice = Invoice.query.filter_by(student_id=student.id, term_id=term.id).first() if term else None
    results = (
        Result.query.filter_by(student_id=student.id, term_id=term.id).all() if term else []
    )
    average = round(sum(float(r.total_score) for r in results) / len(results), 1) if results else None
    return {
        "student": student,
        "invoice": invoice,
        "results": results,
        "average": average,
    }


def parent_dashboard():
    term = _current_term()
    children = []
    if current_user.parent_profile:
        children = [
            _student_summary(link.student, term)
            for link in current_user.parent_profile.children
        ]
    return render_template("dashboard/parent.html", children=children, term=term)


@main_bp.route("/children/<int:student_id>")
@login_required
def view_child(student_id):
    if current_user.role != Role.PARENT:
        abort(403)

    student = Student.query.get_or_404(student_id)
    owns_child = current_user.parent_profile and any(
        link.student_id == student.id for link in current_user.parent_profile.children
    )
    if not owns_child:
        abort(403)

    term = _current_term()
    summary = _student_summary(student, term)
    return render_template("dashboard/child_detail.html", term=term, viewer="parent", **summary)


def student_dashboard():
    student = current_user.student_profile
    if not student:
        return render_template("dashboard/student.html", student=None)

    term = _current_term()
    summary = _student_summary(student, term)
    return render_template("dashboard/child_detail.html", term=term, viewer="student", **summary)
