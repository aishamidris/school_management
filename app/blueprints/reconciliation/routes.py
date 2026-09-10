from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from app.models.user import Role, User
from app.models.academic import AcademicSession, Term
from app.models.people import Staff
from app.models.finance import Invoice, Payment, FeeStructure
from app.utils.decorators import roles_required, permission_required

reconciliation_bp = Blueprint("reconciliation", __name__, template_folder="../../templates/reconciliation")

# Deliberately owner/admin only. This is the oversight tool that watches
# the accountant's activity — an accountant should never be able to view
# (let alone influence) the page that's checking their own work.
OVERSIGHT_ROLES = (Role.OWNER, Role.ADMIN)


def _current_term():
    session = AcademicSession.query.filter_by(is_current=True).first()
    if not session:
        return None
    return Term.query.filter_by(session_id=session.id, is_current=True).first()


@reconciliation_bp.route("/reconciliation")
@login_required
@roles_required(*OVERSIGHT_ROLES)
@permission_required('reconciliation.view')
def dashboard():
    all_terms = Term.query.join(AcademicSession).order_by(AcademicSession.name.desc(), Term.id.desc()).all()

    term_id = request.args.get("term_id", type=int)
    term = Term.query.get(term_id) if term_id else _current_term()

    if not term:
        flash("No current term is set. Select one below, or ask an admin to mark a term as current.", "warning")
        return render_template(
            "reconciliation/dashboard.html",
            term=None, all_terms=all_terms, invoices=[], total_expected=0, total_collected=0,
            total_outstanding=0, collection_rate=0, voided_payments=[], invoice_discrepancies=[],
            accountant_activity=[], discrepancy_count=0,
        )

    invoices = Invoice.query.filter_by(term_id=term.id).all()
    total_expected = sum((inv.net_expected for inv in invoices), start=0)
    total_collected = sum((inv.total_paid for inv in invoices), start=0)
    total_outstanding = total_expected - total_collected
    collection_rate = round(float(total_collected) / float(total_expected) * 100, 1) if total_expected else 0

    voided_payments = (
        Payment.query.join(Invoice)
        .filter(Invoice.term_id == term.id, Payment.is_voided.is_(True))
        .order_by(Payment.voided_at.desc())
        .all()
    )

    # Flag any invoice whose stored expected_amount doesn't match what the
    # class's fee structure says it should be — this is the "does the
    # accountant's number tally with the system record" check.
    invoice_discrepancies = []
    for inv in invoices:
        student = inv.student
        if not student.class_arm_id:
            continue
        structure = FeeStructure.query.filter_by(
            school_class_id=student.class_arm.school_class_id, term_id=term.id
        ).first()
        if structure and inv.expected_amount != structure.total:
            invoice_discrepancies.append({
                "invoice": inv,
                "structure_total": structure.total,
                "difference": inv.expected_amount - structure.total,
            })

    accountants = Staff.query.join(User).filter(User.role == Role.ACCOUNTANT).all()
    accountant_activity = []
    for acc in accountants:
        payments = (
            Payment.query.join(Invoice)
            .filter(Invoice.term_id == term.id, Payment.recorded_by_id == acc.user_id, Payment.is_voided.is_(False))
            .all()
        )
        voided_count = (
            Payment.query.join(Invoice)
            .filter(Invoice.term_id == term.id, Payment.recorded_by_id == acc.user_id, Payment.is_voided.is_(True))
            .count()
        )
        accountant_activity.append({
            "staff": acc,
            "payment_count": len(payments),
            "total_collected": sum((p.amount for p in payments), start=0),
            "voided_count": voided_count,
        })

    discrepancy_count = len(invoice_discrepancies) + len(voided_payments)

    return render_template(
        "reconciliation/dashboard.html",
        term=term,
        all_terms=all_terms,
        invoices=invoices,
        total_expected=total_expected,
        total_collected=total_collected,
        total_outstanding=total_outstanding,
        collection_rate=collection_rate,
        voided_payments=voided_payments,
        invoice_discrepancies=invoice_discrepancies,
        accountant_activity=accountant_activity,
        discrepancy_count=discrepancy_count,
    )
