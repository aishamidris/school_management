from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from datetime import datetime

from app.extensions import db
from app.models.user import Role, User
from app.models.academic import AcademicSession, SchoolClass, ClassArm, Term
from app.models.people import Student, Staff
from app.models.finance import FeeStructure
from app.utils.decorators import roles_required, permission_required
from app.utils.audit import log_action

academics_bp = Blueprint("academics", __name__, template_folder="../../templates/academics")

MANAGE_ROLES = (Role.OWNER, Role.ADMIN)


def _current_session():
    return AcademicSession.query.filter_by(is_current=True).first()


def _teacher_choices():
    return (
        Staff.query.join(User).filter(User.role == Role.TEACHER, Staff.is_active.is_(True))
        .order_by(User.full_name).all()
    )


@academics_bp.route("/academics/classes")
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def list_classes():
    session = _current_session()
    classes = SchoolClass.query.order_by(SchoolClass.order, SchoolClass.name).all()

    # Arm + student counts for the current session, computed up front so the
    # template stays simple (and we don't run N extra queries per row).
    arm_counts, student_counts = {}, {}
    for sc in classes:
        arms_this_session = [a for a in sc.arms if a.session_id == (session.id if session else None)]
        arm_counts[sc.id] = len(arms_this_session)
        student_counts[sc.id] = sum(len(a.students) for a in arms_this_session)

    groups = []
    seen = set()
    for sc in classes:
        g = sc.level_group or "Ungrouped"
        if g not in seen:
            seen.add(g)
            groups.append(g)

    return render_template(
        "academics/classes.html",
        classes=classes,
        session=session,
        arm_counts=arm_counts,
        student_counts=student_counts,
        groups=groups,
        level_group_options=SchoolClass.LEVEL_GROUPS,
    )


@academics_bp.route("/academics/classes/new", methods=["POST"])
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def create_class():
    session = _current_session()
    if not session:
        flash("No current academic session is set — set one up before adding classes.", "danger")
        return redirect(url_for("academics.list_classes"))

    name = request.form.get("name", "").strip()
    level_group = request.form.get("level_group", "").strip() or None
    if level_group == "__custom__":
        level_group = request.form.get("level_group_custom", "").strip() or None
    arm_names_raw = request.form.get("arm_names", "A").strip()

    if not name:
        flash("Class name is required.", "danger")
        return redirect(url_for("academics.list_classes"))

    if SchoolClass.query.filter(db.func.lower(SchoolClass.name) == name.lower()).first():
        flash(f"A class named '{name}' already exists.", "danger")
        return redirect(url_for("academics.list_classes"))

    max_order = db.session.query(db.func.max(SchoolClass.order)).scalar() or 0
    sc = SchoolClass(name=name, level_group=level_group, order=max_order + 1)
    db.session.add(sc)
    db.session.flush()

    arm_names = [a.strip() for a in arm_names_raw.split(",") if a.strip()] or ["A"]
    created_arms = 0
    for arm_name in arm_names:
        if ClassArm.query.filter_by(school_class_id=sc.id, session_id=session.id, name=arm_name).first():
            continue
        db.session.add(ClassArm(school_class_id=sc.id, session_id=session.id, name=arm_name))
        created_arms += 1

    log_action(
        action="class.created",
        entity_type="SchoolClass",
        entity_id=sc.id,
        after={"name": name, "level_group": level_group, "arms": arm_names},
        description=f"{current_user.full_name} created class '{name}' with {created_arms} arm(s)",
    )
    db.session.commit()

    flash(f"Class '{name}' created with {created_arms} arm(s).", "success")
    return redirect(url_for("academics.list_classes"))


@academics_bp.route("/academics/classes/<int:class_id>/edit", methods=["POST"])
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def edit_class(class_id):
    sc = SchoolClass.query.get_or_404(class_id)

    name = request.form.get("name", "").strip()
    level_group = request.form.get("level_group", "").strip() or None
    if level_group == "__custom__":
        level_group = request.form.get("level_group_custom", "").strip() or None
    order = request.form.get("order", type=int)

    if not name:
        flash("Class name is required.", "danger")
        return redirect(url_for("academics.list_classes"))

    duplicate = SchoolClass.query.filter(
        db.func.lower(SchoolClass.name) == name.lower(), SchoolClass.id != sc.id
    ).first()
    if duplicate:
        flash(f"Another class is already named '{name}'.", "danger")
        return redirect(url_for("academics.list_classes"))

    before = {"name": sc.name, "level_group": sc.level_group, "order": sc.order}
    sc.name = name
    sc.level_group = level_group
    if order is not None:
        sc.order = order

    log_action(
        action="class.updated",
        entity_type="SchoolClass",
        entity_id=sc.id,
        before=before,
        after={"name": name, "level_group": level_group, "order": sc.order},
        description=f"{current_user.full_name} updated class '{name}'",
    )
    db.session.commit()

    flash("Class updated.", "success")
    return redirect(url_for("academics.list_classes"))


@academics_bp.route("/academics/classes/<int:class_id>/delete", methods=["POST"])
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def delete_class(class_id):
    sc = SchoolClass.query.get_or_404(class_id)

    student_count = Student.query.join(ClassArm).filter(ClassArm.school_class_id == sc.id).count()
    fee_structure_count = FeeStructure.query.filter_by(school_class_id=sc.id).count()

    if student_count or fee_structure_count:
        flash(
            f"Can't delete '{sc.name}' — it still has {student_count} student(s) and "
            f"{fee_structure_count} fee structure(s) linked to it. Move or remove those first.",
            "danger",
        )
        return redirect(url_for("academics.list_classes"))

    name = sc.name
    log_action(
        action="class.deleted",
        entity_type="SchoolClass",
        entity_id=sc.id,
        before={"name": name},
        description=f"{current_user.full_name} deleted class '{name}'",
    )
    db.session.delete(sc)  # cascades to its (empty) arms
    db.session.commit()

    flash(f"Class '{name}' deleted.", "success")
    return redirect(url_for("academics.list_classes"))


@academics_bp.route("/academics/classes/<int:class_id>")
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def view_class(class_id):
    sc = SchoolClass.query.get_or_404(class_id)
    session = _current_session()
    arms = (
        ClassArm.query.filter_by(school_class_id=sc.id, session_id=session.id if session else None)
        .order_by(ClassArm.name).all()
    )
    return render_template(
        "academics/class_detail.html",
        sc=sc, session=session, arms=arms, teachers=_teacher_choices(),
    )


@academics_bp.route("/academics/classes/<int:class_id>/arms/new", methods=["POST"])
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def add_arm(class_id):
    sc = SchoolClass.query.get_or_404(class_id)
    session = _current_session()
    if not session:
        flash("No current academic session is set.", "danger")
        return redirect(url_for("academics.view_class", class_id=class_id))

    name = request.form.get("name", "").strip()
    class_teacher_id = request.form.get("class_teacher_id", type=int) or None

    if not name:
        flash("Arm name is required.", "danger")
        return redirect(url_for("academics.view_class", class_id=class_id))

    if ClassArm.query.filter_by(school_class_id=sc.id, session_id=session.id, name=name).first():
        flash(f"'{sc.name}{name}' already exists this session.", "danger")
        return redirect(url_for("academics.view_class", class_id=class_id))

    arm = ClassArm(school_class_id=sc.id, session_id=session.id, name=name, class_teacher_id=class_teacher_id)
    db.session.add(arm)

    log_action(
        action="arm.created",
        entity_type="ClassArm",
        after={"class": sc.name, "arm": name},
        description=f"{current_user.full_name} added arm '{sc.name}{name}'",
    )
    db.session.commit()

    flash(f"Arm '{sc.name}{name}' added.", "success")
    return redirect(url_for("academics.view_class", class_id=class_id))


@academics_bp.route("/academics/classes/<int:class_id>/arms/<int:arm_id>/edit", methods=["POST"])
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def edit_arm(class_id, arm_id):
    arm = ClassArm.query.get_or_404(arm_id)
    class_teacher_id = request.form.get("class_teacher_id", type=int) or None

    arm.class_teacher_id = class_teacher_id
    log_action(
        action="arm.updated",
        entity_type="ClassArm",
        entity_id=arm.id,
        after={"class_teacher_id": class_teacher_id},
        description=f"{current_user.full_name} updated class teacher for '{arm.display_name}'",
    )
    db.session.commit()

    flash(f"'{arm.display_name}' updated.", "success")
    return redirect(url_for("academics.view_class", class_id=class_id))


@academics_bp.route("/academics/classes/<int:class_id>/arms/<int:arm_id>/delete", methods=["POST"])
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def delete_arm(class_id, arm_id):
    arm = ClassArm.query.get_or_404(arm_id)

    student_count = Student.query.filter_by(class_arm_id=arm.id).count()
    if student_count:
        flash(f"Can't delete '{arm.display_name}' — it still has {student_count} student(s) in it.", "danger")
        return redirect(url_for("academics.view_class", class_id=class_id))

    name = arm.display_name
    db.session.delete(arm)
    log_action(
        action="arm.deleted",
        entity_type="ClassArm",
        entity_id=arm_id,
        before={"name": name},
        description=f"{current_user.full_name} deleted arm '{name}'",
    )
    db.session.commit()

    flash(f"Arm '{name}' deleted.", "success")
    return redirect(url_for("academics.view_class", class_id=class_id))


@academics_bp.route("/academics/terms")
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def list_terms():
    terms = (
        Term.query.join(AcademicSession)
        .order_by(AcademicSession.name.desc(), Term.id.desc())
        .all()
    )
    return render_template("academics/terms.html", terms=terms)


@academics_bp.route("/academics/terms/<int:term_id>/deadlines", methods=["POST"])
@login_required
@roles_required(*MANAGE_ROLES)
@permission_required("academics.manage")
def set_term_deadlines(term_id):
    term = Term.query.get_or_404(term_id)

    def _parse(raw):
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None

    before = {
        "result_entry_deadline": str(term.result_entry_deadline) if term.result_entry_deadline else None,
        "lesson_plan_deadline": str(term.lesson_plan_deadline) if term.lesson_plan_deadline else None,
    }

    term.result_entry_deadline = _parse(request.form.get("result_entry_deadline"))
    term.lesson_plan_deadline = _parse(request.form.get("lesson_plan_deadline"))

    log_action(
        action="term.deadlines_updated",
        entity_type="Term",
        entity_id=term.id,
        before=before,
        after={
            "result_entry_deadline": str(term.result_entry_deadline) if term.result_entry_deadline else None,
            "lesson_plan_deadline": str(term.lesson_plan_deadline) if term.lesson_plan_deadline else None,
        },
        description=f"{current_user.full_name} updated deadlines for {term.session.name} — {term.name}",
    )
    db.session.commit()

    flash(f"Deadlines saved for {term.name}.", "success")
    return redirect(url_for("academics.list_terms"))
