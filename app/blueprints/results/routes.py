from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role, User
from app.models.academic import AcademicSession, Term, ClassArm, ClassSubject, Subject
from app.models.people import Student, StudentStatus, Staff
from app.models.exam import Result, GradeBand
from app.utils.decorators import roles_required, permission_required
from app.utils.audit import log_action

results_bp = Blueprint("results", __name__, template_folder="../../templates/results")

STAFF_VIEW_ROLES = (Role.OWNER, Role.ADMIN, Role.TEACHER)
ADMIN_ROLES = (Role.OWNER, Role.ADMIN)


def _current_term():
    session = AcademicSession.query.filter_by(is_current=True).first()
    if not session:
        return None
    return Term.query.filter_by(session_id=session.id, is_current=True).first()


def _grade_for_score(score):
    band = (
        GradeBand.query.filter(GradeBand.min_score <= score, GradeBand.max_score >= score)
        .first()
    )
    return band.grade if band else None


# ---------------- Subjects (admin) ----------------

@results_bp.route("/results/subjects/new", methods=["POST"])
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required('results.setup')
def create_subject():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip() or None

    if not name:
        flash("Subject name is required.", "danger")
        return redirect(url_for("results.assign_subjects"))

    if Subject.query.filter_by(name=name).first():
        flash(f"'{name}' already exists.", "warning")
        return redirect(url_for("results.assign_subjects"))

    subject = Subject(name=name, code=code)
    db.session.add(subject)

    log_action(
        action="subject.created",
        entity_type="Subject",
        after={"name": name},
        description=f"{current_user.full_name} added subject '{name}'",
    )
    db.session.commit()

    flash(f"Subject '{name}' added.", "success")
    return redirect(url_for("results.assign_subjects"))


# ---------------- Assign subjects to classes (admin) ----------------

@results_bp.route("/results/assign-subjects", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required('results.setup')
def assign_subjects():
    class_arms = ClassArm.query.join(AcademicSession).filter(AcademicSession.is_current.is_(True)).all()
    subjects = Subject.query.order_by(Subject.name).all()
    teachers = Staff.query.join(User).filter(User.role == Role.TEACHER).all()

    if request.method == "POST":
        class_arm_id = request.form.get("class_arm_id", type=int)
        subject_id = request.form.get("subject_id", type=int)
        teacher_id = request.form.get("teacher_id", type=int) or None

        if not class_arm_id or not subject_id:
            flash("Select both a class and a subject.", "danger")
            return redirect(url_for("results.assign_subjects"))

        existing = ClassSubject.query.filter_by(class_arm_id=class_arm_id, subject_id=subject_id).first()
        if existing:
            flash("That subject is already assigned to this class. Editing assignments is coming soon — remove and re-add for now.", "warning")
            return redirect(url_for("results.assign_subjects"))

        cs = ClassSubject(class_arm_id=class_arm_id, subject_id=subject_id, teacher_id=teacher_id)
        db.session.add(cs)

        log_action(
            action="class_subject.created",
            entity_type="ClassSubject",
            after={"class_arm_id": class_arm_id, "subject_id": subject_id, "teacher_id": teacher_id},
            description=f"{current_user.full_name} assigned a subject to a class",
        )
        db.session.commit()

        flash("Subject assigned to class.", "success")
        return redirect(url_for("results.assign_subjects"))

    assignments = ClassSubject.query.join(ClassArm).join(AcademicSession).filter(AcademicSession.is_current.is_(True)).all()
    return render_template(
        "results/assign_subjects.html",
        class_arms=class_arms, subjects=subjects, teachers=teachers, assignments=assignments,
    )


@results_bp.route("/results/assign-subjects/<int:class_subject_id>/set-teacher", methods=["POST"])
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required('results.setup')
def set_teacher(class_subject_id):
    cs = ClassSubject.query.get_or_404(class_subject_id)
    teacher_id = request.form.get("teacher_id", type=int) or None

    before_teacher = cs.teacher.user.full_name if cs.teacher else None
    cs.teacher_id = teacher_id
    db.session.flush()
    after_teacher = cs.teacher.user.full_name if cs.teacher else None

    log_action(
        action="class_subject.teacher_changed",
        entity_type="ClassSubject",
        entity_id=cs.id,
        before={"teacher": before_teacher},
        after={"teacher": after_teacher},
        description=f"{current_user.full_name} set the teacher for {cs.subject.name} — "
                     f"{cs.class_arm.display_name} to {after_teacher or 'Unassigned'}",
    )
    db.session.commit()

    flash(f"Teacher updated for {cs.subject.name} — {cs.class_arm.display_name}.", "success")
    return redirect(url_for("results.assign_subjects"))


@results_bp.route("/results/assign-subjects/<int:class_subject_id>/remove", methods=["POST"])
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required('results.setup')
def remove_assignment(class_subject_id):
    cs = ClassSubject.query.get_or_404(class_subject_id)
    log_action(
        action="class_subject.removed",
        entity_type="ClassSubject",
        entity_id=cs.id,
        description=f"{current_user.full_name} removed subject assignment "
                     f"{cs.subject.name} from {cs.class_arm.display_name}",
    )
    db.session.delete(cs)
    db.session.commit()
    flash("Assignment removed.", "warning")
    return redirect(url_for("results.assign_subjects"))


# ---------------- Teacher: my classes ----------------

@results_bp.route("/results/my-classes")
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('results.view')
def my_classes():
    if current_user.role == Role.TEACHER:
        if not current_user.staff_profile:
            flash("Your account isn't linked to a staff profile yet. Contact an admin.", "warning")
            return render_template("results/my_classes.html", class_subjects=[])
        class_subjects = ClassSubject.query.filter_by(teacher_id=current_user.staff_profile.id).all()
    else:
        # Owner/Admin see everything, useful for oversight
        class_subjects = ClassSubject.query.all()

    return render_template("results/my_classes.html", class_subjects=class_subjects, term=_current_term())


# ---------------- Score entry ----------------

@results_bp.route("/results/entry/<int:class_subject_id>", methods=["GET", "POST"])
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('results.enter')
def enter_results(class_subject_id):
    class_subject = ClassSubject.query.get_or_404(class_subject_id)
    term = _current_term()

    if not term:
        flash("No current term is set. Ask an admin to mark a term as current.", "danger")
        return redirect(url_for("results.my_classes"))

    # Teachers may only enter results for their own assigned subject
    if current_user.role == Role.TEACHER:
        if not current_user.staff_profile or class_subject.teacher_id != current_user.staff_profile.id:
            flash("You are not assigned to teach this subject.", "danger")
            return redirect(url_for("results.my_classes"))

    students = (
        Student.query.filter_by(class_arm_id=class_subject.class_arm_id, status=StudentStatus.ACTIVE)
        .order_by(Student.full_name)
        .all()
    )

    existing_results = {
        r.student_id: r
        for r in Result.query.filter_by(class_subject_id=class_subject.id, term_id=term.id).all()
    }

    if request.method == "POST":
        updated = 0
        for student in students:
            ca_raw = request.form.get(f"ca_{student.id}", "").strip()
            exam_raw = request.form.get(f"exam_{student.id}", "").strip()

            if not ca_raw and not exam_raw:
                continue  # skip blanks rather than force zero-scoring everyone

            try:
                ca = Decimal(ca_raw) if ca_raw else Decimal("0")
                exam = Decimal(exam_raw) if exam_raw else Decimal("0")
            except InvalidOperation:
                continue

            total = ca + exam
            grade = _grade_for_score(total)

            result = existing_results.get(student.id)
            if result:
                result.ca_score = ca
                result.exam_score = exam
                result.total_score = total
                result.grade = grade
                result.entered_by_id = current_user.id
            else:
                result = Result(
                    student_id=student.id,
                    class_subject_id=class_subject.id,
                    term_id=term.id,
                    ca_score=ca,
                    exam_score=exam,
                    total_score=total,
                    grade=grade,
                    entered_by_id=current_user.id,
                )
                db.session.add(result)
            updated += 1

        log_action(
            action="result.entered",
            entity_type="ClassSubject",
            entity_id=class_subject.id,
            after={"updated_count": updated, "term": term.name, "subject": class_subject.subject.name},
            description=f"{current_user.full_name} entered/updated {updated} result(s) for "
                         f"{class_subject.subject.name} — {class_subject.class_arm.display_name} ({term.name})",
        )
        db.session.commit()

        flash(f"Saved results for {updated} student(s).", "success")
        return redirect(url_for("results.enter_results", class_subject_id=class_subject.id))

    return render_template(
        "results/entry.html",
        class_subject=class_subject,
        students=students,
        existing_results=existing_results,
        term=term,
    )


# ---------------- Grade bands (admin) ----------------

@results_bp.route("/results/grade-bands", methods=["GET", "POST"])
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required('results.setup')
def grade_bands():
    if request.method == "POST":
        try:
            min_score = Decimal(request.form.get("min_score"))
            max_score = Decimal(request.form.get("max_score"))
        except (InvalidOperation, TypeError):
            flash("Enter valid numeric score ranges.", "danger")
            return redirect(url_for("results.grade_bands"))

        grade = request.form.get("grade", "").strip().upper()
        remark = request.form.get("remark", "").strip()

        if not grade or min_score > max_score:
            flash("Check the grade letter and that min is not greater than max.", "danger")
            return redirect(url_for("results.grade_bands"))

        db.session.add(GradeBand(min_score=min_score, max_score=max_score, grade=grade, remark=remark))
        log_action(
            action="grade_band.created",
            entity_type="GradeBand",
            after={"grade": grade, "min": str(min_score), "max": str(max_score)},
            description=f"{current_user.full_name} added grade band {grade} ({min_score}-{max_score})",
        )
        db.session.commit()
        flash("Grade band added.", "success")
        return redirect(url_for("results.grade_bands"))

    bands = GradeBand.query.order_by(GradeBand.min_score.desc()).all()
    return render_template("results/grade_bands.html", bands=bands)


@results_bp.route("/results/grade-bands/<int:band_id>/delete", methods=["POST"])
@login_required
@roles_required(*ADMIN_ROLES)
@permission_required('results.setup')
def delete_grade_band(band_id):
    band = GradeBand.query.get_or_404(band_id)
    log_action(
        action="grade_band.deleted",
        entity_type="GradeBand",
        entity_id=band.id,
        before={"grade": band.grade, "min": str(band.min_score), "max": str(band.max_score)},
        description=f"{current_user.full_name} deleted grade band {band.grade}",
    )
    db.session.delete(band)
    db.session.commit()
    flash("Grade band removed.", "warning")
    return redirect(url_for("results.grade_bands"))


# ---------------- Broadsheet ----------------

@results_bp.route("/results/broadsheet")
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('results.view')
def broadsheet_picker():
    class_arms = ClassArm.query.join(AcademicSession).filter(AcademicSession.is_current.is_(True)).all()
    return render_template("results/broadsheet_picker.html", class_arms=class_arms)


@results_bp.route("/results/broadsheet/<int:class_arm_id>")
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('results.view')
def broadsheet(class_arm_id):
    class_arm = ClassArm.query.get_or_404(class_arm_id)
    term = _current_term()
    if not term:
        flash("No current term is set.", "danger")
        return redirect(url_for("results.broadsheet_picker"))

    students = Student.query.filter_by(class_arm_id=class_arm.id, status=StudentStatus.ACTIVE).order_by(Student.full_name).all()
    class_subjects = ClassSubject.query.filter_by(class_arm_id=class_arm.id).all()

    # Build a lookup: {student_id: {class_subject_id: Result}}
    results = Result.query.filter(
        Result.term_id == term.id,
        Result.class_subject_id.in_([cs.id for cs in class_subjects]) if class_subjects else False,
    ).all()
    grid = {}
    for r in results:
        grid.setdefault(r.student_id, {})[r.class_subject_id] = r

    return render_template(
        "results/broadsheet.html",
        class_arm=class_arm,
        term=term,
        students=students,
        class_subjects=class_subjects,
        grid=grid,
    )
