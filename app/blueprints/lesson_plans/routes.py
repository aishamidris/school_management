from datetime import datetime, date as date_cls
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role
from app.models.academic import ClassSubject
from app.models.lesson_plan import LessonPlan, LessonPlanDay, LessonPlanStep
from app.utils.decorators import roles_required
from app.utils.permissions import has_permission
from app.utils.audit import log_action

lesson_plans_bp = Blueprint("lesson_plans", __name__, template_folder="../../templates/lesson_plans")

STAFF_ROLES = (Role.OWNER, Role.ADMIN, Role.TEACHER)


def _teachable_class_subjects():
    """The (class, subject) combinations the current staff member is
    assigned to teach — what populates the picker on the lesson plan form."""
    if not current_user.staff_profile:
        return []
    return (
        ClassSubject.query.filter_by(teacher_id=current_user.staff_profile.id)
        .join(ClassSubject.class_arm)
        .order_by(ClassSubject.class_arm_id)
        .all()
    )


def _can_edit(plan):
    if current_user.role in (Role.OWNER, Role.ADMIN):
        return True
    return bool(current_user.staff_profile) and plan.teacher_id == current_user.staff_profile.id


def _can_view(plan):
    if _can_edit(plan):
        return True
    return has_permission(current_user, "lessonplans.view_all")


def _parse_days_from_form():
    """Reads the dynamically added/removed Day and Step blocks out of the
    submitted form. Each day block carries a client-generated uid baked
    into its step field names (steps_content_<uid>[], etc.) so days can be
    added/removed/reordered freely in the browser without the server
    needing to track anything beyond submission order."""
    day_uids = request.form.getlist("day_uid[]")
    days_payload = []

    for position, uid in enumerate(day_uids):
        contents = request.form.getlist(f"steps_content_{uid}[]")
        teacher_acts = request.form.getlist(f"steps_teacher_{uid}[]")
        pupil_acts = request.form.getlist(f"steps_pupil_{uid}[]")

        steps_payload = []
        for content, teacher_act, pupil_act in zip(contents, teacher_acts, pupil_acts):
            if not (content.strip() or teacher_act.strip() or pupil_act.strip()):
                continue  # skip a step row the teacher added but left entirely blank
            steps_payload.append((content.strip(), teacher_act.strip(), pupil_act.strip()))

        days_payload.append(steps_payload)

    return days_payload


def _apply_form_to_plan(plan):
    plan.class_subject_id = request.form.get("class_subject_id", type=int)
    date_raw = request.form.get("date", "").strip()
    try:
        plan.date = datetime.strptime(date_raw, "%Y-%m-%d").date()
    except ValueError:
        plan.date = date_cls.today()

    plan.topic = request.form.get("topic", "").strip()
    plan.sub_topic = request.form.get("sub_topic", "").strip()
    plan.behavioral_objective = request.form.get("behavioral_objective", "").strip()
    plan.teaching_methods = request.form.get("teaching_methods", "").strip()
    plan.teaching_aid = request.form.get("teaching_aid", "").strip()
    plan.introduction = request.form.get("introduction", "").strip()
    plan.presentation = request.form.get("presentation", "").strip()
    plan.evaluation = request.form.get("evaluation", "").strip()
    plan.summary = request.form.get("summary", "").strip()
    plan.conclusion = request.form.get("conclusion", "").strip()
    plan.reference = request.form.get("reference", "").strip()

    # Replace the whole days/steps tree — simplest way to honor arbitrary
    # client-side add/remove/reorder without diffing against what's saved.
    plan.days = []
    db.session.flush()

    for day_index, steps_payload in enumerate(_parse_days_from_form()):
        day = LessonPlanDay(order_index=day_index)
        for step_index, (content, teacher_act, pupil_act) in enumerate(steps_payload):
            day.steps.append(LessonPlanStep(
                order_index=step_index,
                content_development=content,
                teacher_activity=teacher_act,
                pupil_activity=pupil_act,
            ))
        plan.days.append(day)


@lesson_plans_bp.route("/lesson-plans")
@login_required
@roles_required(*STAFF_ROLES)
def list_plans():
    can_view_all = has_permission(current_user, "lessonplans.view_all")
    requested = request.args.get("view")

    if requested == "mine":
        view_all = False
    elif requested == "all":
        view_all = True
    else:
        # No explicit choice made: default to "all" only when there's no
        # personal list to fall back to (Owner/Admin accounts aren't
        # linked to a staff profile), so a permitted viewer never lands
        # on a dead-end warning just from opening the page normally.
        view_all = not current_user.staff_profile

    view_all = view_all and can_view_all

    if not view_all and not current_user.staff_profile:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    query = LessonPlan.query
    if not view_all:
        query = query.filter_by(teacher_id=current_user.staff_profile.id)

    plans = query.order_by(LessonPlan.date.desc()).all()

    return render_template(
        "lesson_plans/list.html",
        plans=plans,
        view_all=view_all,
        can_view_all=can_view_all,
    )


@lesson_plans_bp.route("/lesson-plans/new", methods=["GET", "POST"])
@login_required
@roles_required(*STAFF_ROLES)
def new_plan():
    if not current_user.staff_profile:
        flash("Your account isn't linked to a staff profile.", "warning")
        return redirect(url_for("main.dashboard"))

    class_subjects = _teachable_class_subjects()

    if request.method == "POST":
        if not request.form.get("class_subject_id"):
            flash("Please select a class & subject.", "danger")
            return redirect(url_for("lesson_plans.new_plan"))

        plan = LessonPlan(teacher_id=current_user.staff_profile.id)
        _apply_form_to_plan(plan)
        db.session.add(plan)
        db.session.flush()

        log_action(
            action="lessonplans.created",
            entity_type="LessonPlan",
            entity_id=plan.id,
            description=f"{current_user.full_name} created a lesson plan on {plan.topic or 'Untitled topic'}",
        )
        db.session.commit()

        flash("Lesson plan saved.", "success")
        return redirect(url_for("lesson_plans.view_plan", plan_id=plan.id))

    return render_template("lesson_plans/form.html", plan=None, class_subjects=class_subjects, today=date_cls.today())


@lesson_plans_bp.route("/lesson-plans/<int:plan_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required(*STAFF_ROLES)
def edit_plan(plan_id):
    plan = LessonPlan.query.get_or_404(plan_id)
    if not _can_edit(plan):
        abort(403)

    class_subjects = _teachable_class_subjects()
    # Editing a plan created under a class/subject the current user no
    # longer teaches (e.g. an admin editing someone else's plan) — keep it
    # selectable so saving doesn't silently reassign it.
    if plan.class_subject and plan.class_subject not in class_subjects:
        class_subjects = [plan.class_subject] + class_subjects

    if request.method == "POST":
        _apply_form_to_plan(plan)

        log_action(
            action="lessonplans.updated",
            entity_type="LessonPlan",
            entity_id=plan.id,
            description=f"{current_user.full_name} updated the lesson plan on {plan.topic or 'Untitled topic'}",
        )
        db.session.commit()

        flash("Lesson plan updated.", "success")
        return redirect(url_for("lesson_plans.view_plan", plan_id=plan.id))

    return render_template("lesson_plans/form.html", plan=plan, class_subjects=class_subjects, today=plan.date)


@lesson_plans_bp.route("/lesson-plans/<int:plan_id>")
@login_required
@roles_required(*STAFF_ROLES)
def view_plan(plan_id):
    plan = LessonPlan.query.get_or_404(plan_id)
    if not _can_view(plan):
        abort(403)
    return render_template("lesson_plans/view.html", plan=plan, can_edit=_can_edit(plan))


@lesson_plans_bp.route("/lesson-plans/<int:plan_id>/delete", methods=["POST"])
@login_required
@roles_required(*STAFF_ROLES)
def delete_plan(plan_id):
    plan = LessonPlan.query.get_or_404(plan_id)
    if not _can_edit(plan):
        abort(403)

    log_action(
        action="lessonplans.deleted",
        entity_type="LessonPlan",
        entity_id=plan.id,
        description=f"{current_user.full_name} deleted the lesson plan on {plan.topic or 'Untitled topic'}",
    )
    db.session.delete(plan)
    db.session.commit()

    flash("Lesson plan deleted.", "success")
    return redirect(url_for("lesson_plans.list_plans"))
