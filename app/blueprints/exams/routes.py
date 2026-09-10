from datetime import datetime
from collections import OrderedDict
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role
from app.models.academic import AcademicSession, Term, ClassSubject
from app.models.exam import Exam, Question, QuestionOption, QuestionType, AssessmentType
from app.utils.decorators import roles_required, permission_required
from app.utils.audit import log_action
from app.utils.question_parser import parse_pasted_questions

exams_bp = Blueprint("exams", __name__, template_folder="../../templates/exams")

STAFF_VIEW_ROLES = (Role.OWNER, Role.ADMIN, Role.TEACHER)
MANAGER_ROLES = (Role.OWNER, Role.ADMIN)


def _current_term():
    session = AcademicSession.query.filter_by(is_current=True).first()
    if not session:
        return None
    return Term.query.filter_by(session_id=session.id, is_current=True).first()


def _my_class_subjects():
    """Class-subjects the current user is allowed to set exams for."""
    if current_user.role == Role.TEACHER:
        if not current_user.staff_profile:
            return []
        return ClassSubject.query.filter_by(teacher_id=current_user.staff_profile.id).all()
    return ClassSubject.query.all()  # owner/admin can set up exams for anyone


@exams_bp.route("/exams")
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def list_exams():
    class_subject_ids = [cs.id for cs in _my_class_subjects()]
    exams = (
        Exam.query.filter(Exam.class_subject_id.in_(class_subject_ids)).all()
        if class_subject_ids else []
    )
    return render_template("exams/list.html", exams=exams, today=datetime.utcnow().date())


@exams_bp.route("/exams/new", methods=["GET", "POST"])
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def create_exam():
    class_subjects = _my_class_subjects()
    term = _current_term()

    if request.method == "POST":
        class_subject_id = request.form.get("class_subject_id", type=int)
        title = request.form.get("title", "").strip()
        assessment_type = request.form.get("assessment_type", AssessmentType.FINAL)
        total_marks = request.form.get("total_marks", type=float) or 100
        duration = request.form.get("duration_minutes", type=int)
        is_online = bool(request.form.get("is_online"))
        deadline_raw = request.form.get("question_deadline", "").strip()
        question_deadline = None
        if current_user.role in MANAGER_ROLES and deadline_raw:
            question_deadline = datetime.strptime(deadline_raw, "%Y-%m-%d").date()

        allowed_ids = {cs.id for cs in class_subjects}
        if not class_subject_id or class_subject_id not in allowed_ids:
            flash("Select a valid class/subject.", "danger")
            return render_template("exams/form.html", class_subjects=class_subjects)

        if not title:
            flash("Give the exam a title.", "danger")
            return render_template("exams/form.html", class_subjects=class_subjects)

        if not term:
            flash("No current term is set. Ask an admin to mark a term as current.", "danger")
            return redirect(url_for("exams.list_exams"))

        exam = Exam(
            class_subject_id=class_subject_id,
            term_id=term.id,
            title=title,
            assessment_type=assessment_type,
            total_marks=total_marks,
            duration_minutes=duration,
            is_online=is_online,
            question_deadline=question_deadline,
            created_by_id=current_user.id,
        )
        db.session.add(exam)
        db.session.flush()

        log_action(
            action="exam.created",
            entity_type="Exam",
            entity_id=exam.id,
            after={"title": title, "class_subject_id": class_subject_id},
            description=f"{current_user.full_name} created exam '{title}'",
        )
        db.session.commit()

        flash("Exam created. Now add questions — paste them in bulk or add one at a time.", "success")
        return redirect(url_for("exams.view_exam", exam_id=exam.id))

    return render_template("exams/form.html", class_subjects=class_subjects)


@exams_bp.route("/exams/<int:exam_id>")
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def view_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)

    if current_user.role == Role.TEACHER:
        if not current_user.staff_profile or exam.class_subject.teacher_id != current_user.staff_profile.id:
            flash("You don't have access to this exam.", "danger")
            return redirect(url_for("exams.list_exams"))

    total_question_marks = sum((q.marks for q in exam.questions), start=0)

    sections = OrderedDict()
    for q in exam.questions:
        key = q.section or "Ungrouped"
        sections.setdefault(key, []).append(q)

    return render_template(
        "exams/view.html", exam=exam, total_question_marks=total_question_marks,
        sections=sections, today=datetime.utcnow().date(),
    )


@exams_bp.route("/exams/<int:exam_id>/paste", methods=["POST"])
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def paste_questions(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    raw_text = request.form.get("raw_text", "")
    section_name = request.form.get("section_name", "").strip() or None
    default_marks = request.form.get("default_marks", type=float)

    # The parser itself resolves precedence: an explicit "Marks:" line on
    # a question beats a "SECTION A [x marks each]" header in the pasted
    # text, which beats this default_marks fallback from the form.
    parsed = parse_pasted_questions(raw_text, default_marks=default_marks if default_marks is not None else 1)
    if not parsed:
        flash("Couldn't find any questions in that text. Check the format and try again.", "danger")
        return redirect(url_for("exams.view_exam", exam_id=exam.id))

    mcq_missing_answer = 0
    for q in parsed:
        # A question's own in-text section (from a "SECTION A" header)
        # wins; otherwise it falls back to the "Section name" form field,
        # so a teacher can either paste one section at a time with that
        # field, or paste a whole multi-section exam in one go.
        section = q["section"] or section_name

        question = Question(
            exam_id=exam.id,
            subject_id=exam.class_subject.subject_id,
            school_class_id=exam.class_subject.class_arm.school_class_id,
            section=section,
            question_type=QuestionType.MCQ if q["type"] == "mcq" else QuestionType.THEORY,
            prompt=q["prompt"],
            marks=q["marks"],
            marking_guide=q["marking_guide"] or None,
        )
        db.session.add(question)
        db.session.flush()

        if q["type"] == "mcq":
            if not q["answer_letter"]:
                mcq_missing_answer += 1
            for opt in q["options"]:
                db.session.add(QuestionOption(
                    question_id=question.id,
                    label=opt["label"],
                    text=opt["text"],
                    is_correct=(opt["label"] == q["answer_letter"]),
                ))

    log_action(
        action="question.pasted",
        entity_type="Exam",
        entity_id=exam.id,
        after={"count": len(parsed), "section": section_name},
        description=f"{current_user.full_name} pasted {len(parsed)} question(s) into '{exam.title}'"
                     f"{f' (section: {section_name})' if section_name else ''}",
    )
    db.session.commit()

    msg = f"Added {len(parsed)} question(s) from your paste."
    if mcq_missing_answer:
        msg += f" Note: {mcq_missing_answer} multiple-choice question(s) had no 'Answer:' line — mark the correct option manually."
    flash(msg, "success" if not mcq_missing_answer else "warning")
    return redirect(url_for("exams.view_exam", exam_id=exam.id))


@exams_bp.route("/exams/<int:exam_id>/questions/new", methods=["POST"])
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def add_question(exam_id):
    exam = Exam.query.get_or_404(exam_id)

    question_type = request.form.get("question_type", QuestionType.MCQ)
    prompt = request.form.get("prompt", "").strip()
    marks = request.form.get("marks", type=float) or 1
    section = request.form.get("section", "").strip() or None

    if not prompt:
        flash("Enter the question text.", "danger")
        return redirect(url_for("exams.view_exam", exam_id=exam.id))

    question = Question(
        exam_id=exam.id,
        subject_id=exam.class_subject.subject_id,
        school_class_id=exam.class_subject.class_arm.school_class_id,
        section=section,
        question_type=question_type,
        prompt=prompt,
        marks=marks,
    )

    if question_type == QuestionType.MCQ:
        correct_index = request.form.get("correct_option")
        labels = ["A", "B", "C", "D"]
        db.session.add(question)
        db.session.flush()
        for i, label in enumerate(labels):
            text = request.form.get(f"option_{label}", "").strip()
            if not text:
                continue
            db.session.add(QuestionOption(
                question_id=question.id, label=label, text=text, is_correct=(label == correct_index)
            ))
    else:
        question.marking_guide = request.form.get("marking_guide", "").strip() or None
        db.session.add(question)

    log_action(
        action="question.added",
        entity_type="Exam",
        entity_id=exam.id,
        description=f"{current_user.full_name} added a question to '{exam.title}'",
    )
    db.session.commit()

    flash("Question added.", "success")
    return redirect(url_for("exams.view_exam", exam_id=exam.id))


@exams_bp.route("/exams/<int:exam_id>/questions/<int:question_id>/delete", methods=["POST"])
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def delete_question(exam_id, question_id):
    question = Question.query.get_or_404(question_id)
    log_action(
        action="question.deleted",
        entity_type="Question",
        entity_id=question.id,
        description=f"{current_user.full_name} deleted a question from exam #{exam_id}",
    )
    db.session.delete(question)
    db.session.commit()
    flash("Question removed.", "warning")
    return redirect(url_for("exams.view_exam", exam_id=exam_id))


# ---------------- Deadline (owner/admin assign to a teacher's exam) ----------------

@exams_bp.route("/exams/<int:exam_id>/set-deadline", methods=["POST"])
@login_required
@roles_required(*MANAGER_ROLES)
def set_deadline(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    raw = request.form.get("question_deadline", "").strip()

    before = {"question_deadline": str(exam.question_deadline) if exam.question_deadline else None}
    exam.question_deadline = datetime.strptime(raw, "%Y-%m-%d").date() if raw else None

    log_action(
        action="exam.deadline_set",
        entity_type="Exam",
        entity_id=exam.id,
        before=before,
        after={"question_deadline": raw or None},
        description=f"{current_user.full_name} set the question deadline for '{exam.title}' to "
                     f"{raw or 'none'} (teacher: {exam.class_subject.teacher.user.full_name if exam.class_subject.teacher else 'unassigned'})",
    )
    db.session.commit()

    flash("Deadline updated." if raw else "Deadline removed.", "success")
    return redirect(url_for("exams.view_exam", exam_id=exam.id))


# ---------------- Delete (owner/admin only) ----------------

@exams_bp.route("/exams/<int:exam_id>/delete", methods=["POST"])
@login_required
@roles_required(*MANAGER_ROLES)
def delete_exam(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    title = exam.title

    log_action(
        action="exam.deleted",
        entity_type="Exam",
        entity_id=exam.id,
        before={"title": title, "question_count": len(exam.questions)},
        description=f"{current_user.full_name} deleted exam '{title}' and its {len(exam.questions)} question(s)",
    )
    db.session.delete(exam)  # cascades to Questions and QuestionOptions
    db.session.commit()

    flash(f"Exam '{title}' deleted.", "warning")
    return redirect(url_for("exams.list_exams"))


# ---------------- Print ----------------

@exams_bp.route("/exams/<int:exam_id>/print")
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def print_paper(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    sections = OrderedDict()
    for q in exam.questions:
        sections.setdefault(q.section or "Ungrouped", []).append(q)
    return render_template("exams/print_paper.html", exam=exam, sections=sections)


@exams_bp.route("/exams/<int:exam_id>/print-answer-key")
@login_required
@roles_required(*STAFF_VIEW_ROLES)
@permission_required('exams.manage')
def print_answer_key(exam_id):
    exam = Exam.query.get_or_404(exam_id)
    sections = OrderedDict()
    for q in exam.questions:
        sections.setdefault(q.section or "Ungrouped", []).append(q)
    return render_template("exams/print_answer_key.html", exam=exam, sections=sections)
