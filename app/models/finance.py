from datetime import datetime
from app.extensions import db


class PaymentStatus:
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    OUTSTANDING = "outstanding"
    OVERDUE = "overdue"
    WAIVED = "waived"
    SCHOLARSHIP = "scholarship"


class FeeStructure(db.Model):
    """Defines what a class owes for a given term, e.g. JSS2 / First Term."""
    __tablename__ = "fee_structures"

    id = db.Column(db.Integer, primary_key=True)
    school_class_id = db.Column(db.Integer, db.ForeignKey("school_classes.id"), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id"), nullable=False)

    items = db.relationship("FeeItem", backref="fee_structure", cascade="all, delete-orphan")
    school_class = db.relationship("SchoolClass")
    term = db.relationship("Term")

    __table_args__ = (
        db.UniqueConstraint("school_class_id", "term_id", name="uq_fee_structure"),
    )

    @property
    def total(self):
        return sum(item.amount for item in self.items)


class FeeItem(db.Model):
    """A single line item within a fee structure, e.g. 'Tuition — ₦100,000'."""
    __tablename__ = "fee_items"

    id = db.Column(db.Integer, primary_key=True)
    fee_structure_id = db.Column(db.Integer, db.ForeignKey("fee_structures.id"), nullable=False)
    label = db.Column(db.String(80), nullable=False)  # "Tuition", "Books", "Transport"
    amount = db.Column(db.Numeric(12, 2), nullable=False)


class Invoice(db.Model):
    """A student's bill for a specific term — auto-generated from the
    class's FeeStructure, but stored per-student so waivers/scholarships
    and edits don't affect the whole class."""
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id"), nullable=False)

    expected_amount = db.Column(db.Numeric(12, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(12, 2), default=0)  # scholarship/waiver
    status = db.Column(db.String(20), default=PaymentStatus.OUTSTANDING)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship("Student")
    term = db.relationship("Term")
    payments = db.relationship("Payment", backref="invoice", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("student_id", "term_id", name="uq_invoice_per_term"),
    )

    @property
    def net_expected(self):
        return self.expected_amount - self.discount_amount

    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments if not p.is_voided)

    @property
    def outstanding(self):
        return self.net_expected - self.total_paid


class Payment(db.Model):
    """A single payment against an invoice. Once a term is closed
    (Term.is_closed), these should not be edited directly — only
    voided with a reason, which preserves the audit trail."""
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(30))  # "Transfer", "Cash", "Card", "Online"
    receipt_number = db.Column(db.String(40), unique=True)

    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    is_voided = db.Column(db.Boolean, default=False)
    void_reason = db.Column(db.String(255))
    voided_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    voided_at = db.Column(db.DateTime, nullable=True)

    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])
    voided_by = db.relationship("User", foreign_keys=[voided_by_id])


class Expense(db.Model):
    """Needed so the owner dashboard can show Net Income, not just
    Revenue. Revenue - Expenses = Net Income."""
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.id"), nullable=True)
    category = db.Column(db.String(60), nullable=False)  # "Salaries", "Electricity", "Repairs"
    description = db.Column(db.String(255))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
