from flask import Blueprint, render_template
from flask_login import login_required, current_user

from app.models.user import Role
from app.models.people import Student, Staff
from app.models.finance import Invoice
from app.models.tasks_comms import Task, TaskStatus

main_bp = Blueprint("main", __name__, template_folder="../../templates/dashboard")


@main_bp.route("/")
@login_required
def dashboard():
    if current_user.role in (Role.OWNER, Role.ADMIN):
        return owner_admin_dashboard()
    elif current_user.role == Role.ACCOUNTANT:
        return accountant_dashboard()
    elif current_user.role == Role.TEACHER:
        return teacher_dashboard()
    elif current_user.role == Role.PARENT:
        return parent_dashboard()
    elif current_user.role == Role.STUDENT:
        return student_dashboard()
    return render_template("dashboard/generic.html")


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
    return render_template("dashboard/accountant.html")


def teacher_dashboard():
    return render_template("dashboard/teacher.html")


def parent_dashboard():
    return render_template("dashboard/parent.html")


def student_dashboard():
    return render_template("dashboard/student.html")
