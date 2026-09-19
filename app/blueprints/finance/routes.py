from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import Role
from app.models.academic import AcademicSession, Term, SchoolClass, ClassArm
from app.models.people import Student, StudentStatus
from app.models.finance import FeeStructure, FeeItem, Invoice, Payment, PaymentStatus
from app.utils.decorators import roles_required, permission_required
from app.utils.audit import log_action

finance_bp = Blueprint("finance", __name__, template_folder="../../templates/finance")

STRUCTURE_EDITOR_ROLES = (Role.OWNER, Role.ADMIN)
FINANCE_ROLES = (Role.OWNER, Role.ADMIN, Role.ACCOUNTANT)


def _current_session():
    return AcademicSession.query.filter_by(is_current=True).first()


def _current_session_terms():
    session = _current_session()
    return Term.query.filter_by(session_id=session.id).all() if session else []


def _update_invoice_status(invoice):
    """Recompute status from actual (non-voided) payments. Call this
    after any payment is recorded or voided."""
    if invoice.outstanding <= 0:
        invoice.status = PaymentStatus.PAID
    elif invoice.total_paid > 0:
        invoice.status = PaymentStatus.PARTIALLY_PAID
    else:
        invoice.status = PaymentStatus.OUTSTANDING


def _generate_receipt_number():
    count = Payment.query.count() + 1
    candidate = f"REC-{count:06d}"
    while Payment.query.filter_by(receipt_number=candidate).first():
        count += 1
        candidate = f"REC-{count:06d}"
    return candidate


# ---------------- Fee Structures ----------------

@finance_bp.route("/finance/fee-structures")
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.view')
def list_fee_structures():
    structures = FeeStructure.query.join(Term).join(SchoolClass).all()
    return render_template("finance/fee_structure_list.html", structures=structures)


@finance_bp.route("/finance/fee-structures/new", methods=["GET", "POST"])
@login_required
@roles_required(*STRUCTURE_EDITOR_ROLES)
@permission_required('fees.manage')
def create_fee_structure():
    classes = SchoolClass.query.order_by(SchoolClass.order).all()
    terms = _current_session_terms()
    level_groups = sorted({c.level_group for c in classes if c.level_group})

    if request.method == "POST":
        target_mode = request.form.get("target_mode", "single")
        term_id = request.form.get("term_id", type=int)
        labels = request.form.getlist("item_label[]")
        amounts = request.form.getlist("item_amount[]")

        if target_mode == "group":
            level_group = request.form.get("level_group", "").strip()
            target_classes = SchoolClass.query.filter_by(level_group=level_group).all() if level_group else []
        elif target_mode == "multi":
            class_ids = request.form.getlist("class_ids[]", type=int)
            target_classes = SchoolClass.query.filter(SchoolClass.id.in_(class_ids)).all() if class_ids else []
        else:
            single_id = request.form.get("school_class_id", type=int)
            target_classes = SchoolClass.query.filter_by(id=single_id).all() if single_id else []

        if not target_classes or not term_id:
            flash("Please select a term and at least one class (or a level group).", "danger")
            return render_template("finance/fee_structure_form.html", classes=classes, terms=terms, level_groups=level_groups)

        items = []
        for label, amount_raw in zip(labels, amounts):
            label = label.strip()
            if not label or not amount_raw:
                continue
            try:
                amount = Decimal(amount_raw)
            except InvalidOperation:
                continue
            items.append((label, amount))

        if not items:
            flash("Add at least one fee item with a label and amount.", "danger")
            return render_template("finance/fee_structure_form.html", classes=classes, terms=terms, level_groups=level_groups)

        created_ids, skipped_names = [], []
        for sc in target_classes:
            existing = FeeStructure.query.filter_by(school_class_id=sc.id, term_id=term_id).first()
            if existing:
                skipped_names.append(sc.name)
                continue

            structure = FeeStructure(school_class_id=sc.id, term_id=term_id)
            db.session.add(structure)
            db.session.flush()
            for label, amount in items:
                db.session.add(FeeItem(fee_structure_id=structure.id, label=label, amount=amount))
            created_ids.append(structure.id)

        log_action(
            action="fee_structure.created",
            entity_type="FeeStructure",
            after={"term_id": term_id, "created": len(created_ids), "skipped": skipped_names},
            description=f"{current_user.full_name} created {len(created_ids)} fee structure(s) "
                        f"with {len(items)} item(s) each" + (f"; skipped {len(skipped_names)} (already existed)" if skipped_names else ""),
        )
        db.session.commit()

        if skipped_names:
            flash(f"Skipped {len(skipped_names)} class(es) that already had a fee structure this term: {', '.join(skipped_names)}.", "warning")

        if not created_ids:
            flash("No fee structures were created — every selected class already had one for this term.", "warning")
            return redirect(url_for("finance.list_fee_structures"))

        flash(f"Created {len(created_ids)} fee structure(s).", "success")
        if len(created_ids) == 1:
            return redirect(url_for("finance.view_fee_structure", structure_id=created_ids[0]))
        return redirect(url_for("finance.view_fee_structure_group", ids=",".join(str(i) for i in created_ids)))

    return render_template("finance/fee_structure_form.html", classes=classes, terms=terms, level_groups=level_groups)


@finance_bp.route("/finance/fee-structures/group")
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.view')
def view_fee_structure_group():
    ids_raw = request.args.get("ids", "")
    try:
        ids = [int(i) for i in ids_raw.split(",") if i.strip()]
    except ValueError:
        ids = []

    structures = FeeStructure.query.filter(FeeStructure.id.in_(ids)).all() if ids else []

    rows = []
    for structure in structures:
        student_count = (
            Student.query.join(ClassArm)
            .filter(ClassArm.school_class_id == structure.school_class_id, Student.status == StudentStatus.ACTIVE)
            .count()
        )
        existing_invoice_count = (
            Invoice.query.join(Student).join(ClassArm)
            .filter(ClassArm.school_class_id == structure.school_class_id, Invoice.term_id == structure.term_id)
            .count()
        )
        rows.append({"structure": structure, "student_count": student_count, "existing_invoice_count": existing_invoice_count})

    return render_template("finance/fee_structure_group_view.html", rows=rows)


@finance_bp.route("/finance/fee-structures/group/generate-invoices", methods=["POST"])
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.manage')
def generate_invoices_group():
    ids_raw = request.form.get("ids", "")
    try:
        ids = [int(i) for i in ids_raw.split(",") if i.strip()]
    except ValueError:
        ids = []

    structures = FeeStructure.query.filter(FeeStructure.id.in_(ids)).all() if ids else []

    total_created, total_skipped = 0, 0
    for structure in structures:
        students = (
            Student.query.join(ClassArm)
            .filter(ClassArm.school_class_id == structure.school_class_id, Student.status == StudentStatus.ACTIVE)
            .all()
        )
        for student in students:
            existing = Invoice.query.filter_by(student_id=student.id, term_id=structure.term_id).first()
            if existing:
                total_skipped += 1
                continue
            db.session.add(Invoice(
                student_id=student.id, term_id=structure.term_id,
                expected_amount=structure.total, status=PaymentStatus.OUTSTANDING,
            ))
            total_created += 1

    log_action(
        action="invoice.batch_generated",
        entity_type="FeeStructure",
        after={"structure_ids": ids, "created": total_created, "skipped": total_skipped},
        description=f"{current_user.full_name} generated {total_created} invoice(s) across {len(structures)} class(es); {total_skipped} already existed",
    )
    db.session.commit()

    flash(f"Generated {total_created} invoice(s) across {len(structures)} class(es). {total_skipped} already existed.", "success")
    return redirect(url_for("finance.view_fee_structure_group", ids=ids_raw))


@finance_bp.route("/finance/fee-structures/<int:structure_id>")
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.view')
def view_fee_structure(structure_id):
    structure = FeeStructure.query.get_or_404(structure_id)

    # How many active students are in this class (across all arms), and how
    # many already have an invoice for this term — so the admin knows what
    # "Generate Invoices" is about to do before clicking it.
    student_count = (
        Student.query.join(ClassArm)
        .filter(ClassArm.school_class_id == structure.school_class_id, Student.status == StudentStatus.ACTIVE)
        .count()
    )
    existing_invoice_count = (
        Invoice.query.join(Student).join(ClassArm)
        .filter(ClassArm.school_class_id == structure.school_class_id, Invoice.term_id == structure.term_id)
        .count()
    )

    return render_template(
        "finance/fee_structure_view.html",
        structure=structure,
        student_count=student_count,
        existing_invoice_count=existing_invoice_count,
    )


@finance_bp.route("/finance/fee-structures/<int:structure_id>/generate-invoices", methods=["POST"])
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.manage')
def generate_invoices(structure_id):
    structure = FeeStructure.query.get_or_404(structure_id)

    students = (
        Student.query.join(ClassArm)
        .filter(ClassArm.school_class_id == structure.school_class_id, Student.status == StudentStatus.ACTIVE)
        .all()
    )

    created = 0
    skipped = 0
    for student in students:
        existing = Invoice.query.filter_by(student_id=student.id, term_id=structure.term_id).first()
        if existing:
            skipped += 1
            continue
        invoice = Invoice(
            student_id=student.id,
            term_id=structure.term_id,
            expected_amount=structure.total,
            status=PaymentStatus.OUTSTANDING,
        )
        db.session.add(invoice)
        created += 1

    log_action(
        action="invoice.batch_generated",
        entity_type="FeeStructure",
        entity_id=structure.id,
        after={"created": created, "skipped": skipped},
        description=f"{current_user.full_name} generated {created} invoice(s) from fee structure "
                     f"({structure.school_class.name}, {structure.term.name}); {skipped} already existed",
    )
    db.session.commit()

    flash(f"Generated {created} invoice(s). {skipped} student(s) already had an invoice for this term.", "success")
    return redirect(url_for("finance.view_fee_structure", structure_id=structure.id))


# ---------------- Invoices ----------------

@finance_bp.route("/finance/invoices")
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.view')
def list_invoices():
    term_filter = request.args.get("term_id", type=int)
    status_filter = request.args.get("status", "all")
    search = request.args.get("q", "").strip()

    query = Invoice.query.join(Student)
    if term_filter:
        query = query.filter(Invoice.term_id == term_filter)
    if status_filter != "all":
        query = query.filter(Invoice.status == status_filter)
    if search:
        like = f"%{search}%"
        query = query.filter((Student.full_name.ilike(like)) | (Student.admission_number.ilike(like)))

    invoices = query.order_by(Student.full_name).all()
    terms = _current_session_terms()

    return render_template(
        "finance/invoice_list.html",
        invoices=invoices,
        terms=terms,
        term_filter=term_filter,
        status_filter=status_filter,
        search=search,
    )


@finance_bp.route("/finance/invoices/<int:invoice_id>")
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.view')
def view_invoice(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    return render_template("finance/invoice_view.html", invoice=invoice)


# ---------------- Payments ----------------

@finance_bp.route("/finance/invoices/<int:invoice_id>/payments", methods=["POST"])
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('payments.record')
def record_payment(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.term.is_closed:
        flash("This term is closed. Payments cannot be recorded — ask the owner/admin to reopen it first.", "danger")
        return redirect(url_for("finance.view_invoice", invoice_id=invoice.id))

    amount_raw = request.form.get("amount", "")
    try:
        amount = Decimal(amount_raw)
    except InvalidOperation:
        flash("Enter a valid payment amount.", "danger")
        return redirect(url_for("finance.view_invoice", invoice_id=invoice.id))

    if amount <= 0:
        flash("Payment amount must be greater than zero.", "danger")
        return redirect(url_for("finance.view_invoice", invoice_id=invoice.id))

    receipt_number = _generate_receipt_number()
    payment = Payment(
        invoice_id=invoice.id,
        amount=amount,
        method=request.form.get("method", "Cash"),
        receipt_number=receipt_number,
        recorded_by_id=current_user.id,
    )
    db.session.add(payment)
    db.session.flush()

    _update_invoice_status(invoice)

    log_action(
        action="payment.recorded",
        entity_type="Payment",
        entity_id=payment.id,
        after={"amount": str(amount), "method": payment.method, "receipt_number": receipt_number,
               "student": invoice.student.full_name},
        description=f"{current_user.full_name} recorded a payment of ₦{amount:,.0f} for "
                     f"{invoice.student.full_name} (Receipt {receipt_number})",
    )
    db.session.commit()

    flash(f"Payment of ₦{amount:,.0f} recorded. Receipt number: {receipt_number}.", "success")
    return redirect(url_for("finance.view_invoice", invoice_id=invoice.id))


@finance_bp.route("/finance/payments/<int:payment_id>/void", methods=["POST"])
@login_required
@roles_required(Role.OWNER, Role.ADMIN)  # deliberately NOT accountant — accountants cannot void their own entries
@permission_required('payments.void')
def void_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    reason = request.form.get("reason", "").strip()

    if not reason:
        flash("A reason is required to void a payment.", "danger")
        return redirect(url_for("finance.view_invoice", invoice_id=payment.invoice_id))

    if payment.is_voided:
        flash("This payment is already voided.", "warning")
        return redirect(url_for("finance.view_invoice", invoice_id=payment.invoice_id))

    before = {"amount": str(payment.amount), "is_voided": False}

    payment.is_voided = True
    payment.void_reason = reason
    payment.voided_by_id = current_user.id
    payment.voided_at = datetime.utcnow()

    _update_invoice_status(payment.invoice)

    log_action(
        action="payment.voided",
        entity_type="Payment",
        entity_id=payment.id,
        before=before,
        after={"is_voided": True, "reason": reason},
        description=f"{current_user.full_name} voided payment {payment.receipt_number} "
                     f"(₦{payment.amount:,.0f}) — reason: {reason}",
    )
    db.session.commit()

    flash(f"Payment {payment.receipt_number} has been voided.", "warning")
    return redirect(url_for("finance.view_invoice", invoice_id=payment.invoice_id))


@finance_bp.route("/finance/payments/<int:payment_id>/receipt")
@login_required
@roles_required(*FINANCE_ROLES)
@permission_required('fees.view')
def view_receipt(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    return render_template("finance/receipt.html", payment=payment)
