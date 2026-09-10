"""Populates a realistic demo dataset on top of the base seed, so a
free-tier deployment (which can lose its database on every restart)
always comes back looking like a real, in-use school system rather than
an empty shell.

Deliberately includes one VOIDED payment — that's the single feature
that differentiates this app from generic school software, so the demo
should never be caught without something to show on the Reconciliation
page.

Idempotent: skips entirely if demo data already looks present, so
calling this twice doesn't duplicate everything.
"""
from datetime import date, timedelta, datetime
from decimal import Decimal

from app.extensions import db
from app.models.user import User, Role
from app.models.academic import AcademicSession, Term, SchoolClass, ClassArm, Subject, ClassSubject
from app.models.people import Student, StudentStatus, ParentProfile, StudentGuardian, Staff
from app.models.finance import FeeStructure, FeeItem, Invoice, Payment, PaymentStatus
from app.models.exam import Exam, Question, QuestionOption, Result, GradeBand, QuestionType, AssessmentType
from app.models.attendance import StudentAttendance, StaffAttendance, AttendanceStatus

DEMO_MARKER_EMAIL = "admin@demo.school"


def _grade_for_score(score):
    band = GradeBand.query.filter(GradeBand.min_score <= score, GradeBand.max_score >= score).first()
    return band.grade if band else None


def _make_staff(role, full_name, phone, designation):
    user = User(role=role, full_name=full_name, phone=phone, email=phone.replace("0", "") + "@demo.school")
    user.set_password("Demo123!")
    db.session.add(user)
    db.session.flush()
    staff = Staff(user_id=user.id, staff_id_number=f"STF/DEMO/{user.id:04d}", designation=designation, date_employed=date.today())
    db.session.add(staff)
    db.session.flush()
    return staff


def _make_student(full_name, admission_no, class_arm, gender, guardian_name, guardian_phone):
    student = Student(
        full_name=full_name, admission_number=admission_no, class_arm_id=class_arm.id,
        gender=gender, admission_date=date.today() - timedelta(days=200), status=StudentStatus.ACTIVE,
    )
    db.session.add(student)
    db.session.flush()

    parent_user = User.query.filter_by(phone=guardian_phone).first()
    if not parent_user:
        parent_user = User(role=Role.PARENT, full_name=guardian_name, phone=guardian_phone)
        parent_user.set_password("Demo123!")
        db.session.add(parent_user)
        db.session.flush()
        db.session.add(ParentProfile(user_id=parent_user.id))
        db.session.flush()
    parent_profile = parent_user.parent_profile or ParentProfile(user_id=parent_user.id)
    if not parent_user.parent_profile:
        db.session.add(parent_profile)
        db.session.flush()

    db.session.add(StudentGuardian(
        student_id=student.id, parent_profile_id=parent_profile.id,
        relationship_type="Parent", is_primary_contact=True,
    ))
    return student


def seed_demo_data():
    """Call from inside an active app context, after seed_base_data()."""
    if User.query.filter_by(email=DEMO_MARKER_EMAIL).first():
        print("Demo data already present, skipping.")
        return

    session = AcademicSession.query.filter_by(is_current=True).first()
    term = Term.query.filter_by(session_id=session.id, is_current=True).first()

    jss1a = ClassArm.query.join(SchoolClass).filter(SchoolClass.name == "JSS 1", ClassArm.name == "A").first()
    jss2a = ClassArm.query.join(SchoolClass).filter(SchoolClass.name == "JSS 2", ClassArm.name == "A").first()
    primary3a = ClassArm.query.join(SchoolClass).filter(SchoolClass.name == "Primary 3", ClassArm.name == "A").first()

    maths = Subject.query.filter_by(name="Mathematics").first()
    english = Subject.query.filter_by(name="English Language").first()

    # --- Staff ---
    admin = _make_staff(Role.ADMIN, "Ngozi Adeyemi", "08011110001", "School Administrator")
    admin.user.email = DEMO_MARKER_EMAIL  # marker used to detect "already seeded"
    accountant = _make_staff(Role.ACCOUNTANT, "Bashir Yusuf", "08011110002", "Head Accountant")
    teacher1 = _make_staff(Role.TEACHER, "Funmilayo Okoro", "08011110003", "Mathematics Teacher")
    teacher2 = _make_staff(Role.TEACHER, "David Eze", "08011110004", "English Teacher")

    # --- Subject assignments ---
    cs_maths_jss1a = ClassSubject(class_arm_id=jss1a.id, subject_id=maths.id, teacher_id=teacher1.id)
    cs_english_jss1a = ClassSubject(class_arm_id=jss1a.id, subject_id=english.id, teacher_id=teacher2.id)
    db.session.add_all([cs_maths_jss1a, cs_english_jss1a])
    db.session.flush()

    # --- Students across different levels, so the demo shows the full class range ---
    students_data = [
        ("Aisha Bello", jss1a, "Female", "Mrs. Bello", "08022220001"),
        ("Chidinma Okafor", jss1a, "Female", "Mr. Okafor", "08022220002"),
        ("Emeka Nwosu", jss1a, "Male", "Mrs. Nwosu", "08022220003"),
        ("Fatima Sani", jss1a, "Female", "Alhaji Sani", "08022220004"),
        ("Ibrahim Musa", jss2a, "Male", "Mallam Musa", "08022220005"),
        ("Grace Adamu", jss2a, "Female", "Mr. Adamu", "08022220006"),
        ("Tunde Bakare", primary3a, "Male", "Mrs. Bakare", "08022220007"),
        ("Blessing Okon", primary3a, "Female", "Mr. Okon", "08022220008"),
    ]
    students = []
    for i, (name, arm, gender, gname, gphone) in enumerate(students_data):
        s = _make_student(name, f"STU/2026/{i+1:04d}", arm, gender, gname, gphone)
        students.append(s)
    db.session.flush()

    # --- Fee structure + invoices for JSS 1A ---
    structure = FeeStructure(school_class_id=jss1a.school_class_id, term_id=term.id)
    db.session.add(structure)
    db.session.flush()
    db.session.add_all([
        FeeItem(fee_structure_id=structure.id, label="Tuition", amount=Decimal("80000")),
        FeeItem(fee_structure_id=structure.id, label="Books", amount=Decimal("15000")),
        FeeItem(fee_structure_id=structure.id, label="Transport", amount=Decimal("20000")),
    ])
    db.session.flush()
    total_fee = Decimal("115000")

    jss1a_students = [s for s in students if s.class_arm_id == jss1a.id]
    invoices = []
    for s in jss1a_students:
        inv = Invoice(student_id=s.id, term_id=term.id, expected_amount=total_fee, status=PaymentStatus.OUTSTANDING)
        db.session.add(inv)
        invoices.append(inv)
    db.session.flush()

    def _record_payment(invoice, amount, recorded_by, days_ago=3):
        p = Payment(
            invoice_id=invoice.id, amount=Decimal(amount), method="Transfer",
            receipt_number=f"REC-DEMO-{invoice.id:04d}-{days_ago}",
            recorded_by_id=recorded_by.user_id,
            recorded_at=datetime.utcnow() - timedelta(days=days_ago),
        )
        db.session.add(p)
        db.session.flush()
        return p

    _record_payment(invoices[0], "115000", accountant, days_ago=10)   # fully paid
    _record_payment(invoices[1], "60000", accountant, days_ago=8)     # partially paid
    # invoices[2]: left fully outstanding
    voided_payment = _record_payment(invoices[3], "50000", accountant, days_ago=5)

    for inv, paid in zip(invoices[:2], [Decimal("115000"), Decimal("60000")]):
        inv.status = PaymentStatus.PAID if paid >= inv.expected_amount else PaymentStatus.PARTIALLY_PAID

    # The voided payment: recorded by the accountant, then reversed by
    # admin with a reason on file — exactly what the Reconciliation page
    # is built to surface.
    voided_payment.is_voided = True
    voided_payment.void_reason = "Duplicate entry — parent's transfer was already recorded under a receipt earlier that day."
    voided_payment.voided_by_id = admin.user_id
    voided_payment.voided_at = datetime.utcnow() - timedelta(days=4)
    invoices[3].status = PaymentStatus.OUTSTANDING

    # --- Results for JSS 1A Mathematics ---
    for s in jss1a_students:
        ca = Decimal("22")
        exam_score = Decimal("55") if s.full_name != "Fatima Sani" else Decimal("30")
        total = ca + exam_score
        db.session.add(Result(
            student_id=s.id, class_subject_id=cs_maths_jss1a.id, term_id=term.id,
            ca_score=ca, exam_score=exam_score, total_score=total,
            grade=_grade_for_score(total), entered_by_id=teacher1.user_id,
        ))

    # --- A demo exam with a couple of pasted-style questions ---
    exam = Exam(
        class_subject_id=cs_maths_jss1a.id, term_id=term.id, title="First Term Mid-Term Test",
        assessment_type=AssessmentType.MID_TERM, total_marks=Decimal("20"), created_by_id=teacher1.user_id,
        question_deadline=date.today() + timedelta(days=7),
    )
    db.session.add(exam)
    db.session.flush()

    q1 = Question(exam_id=exam.id, subject_id=maths.id, school_class_id=jss1a.school_class_id,
                   question_type=QuestionType.MCQ, prompt="What is 12 x 8?", marks=Decimal("2"))
    db.session.add(q1)
    db.session.flush()
    db.session.add_all([
        QuestionOption(question_id=q1.id, label="A", text="96", is_correct=True),
        QuestionOption(question_id=q1.id, label="B", text="86", is_correct=False),
        QuestionOption(question_id=q1.id, label="C", text="106", is_correct=False),
        QuestionOption(question_id=q1.id, label="D", text="90", is_correct=False),
    ])
    q2 = Question(exam_id=exam.id, subject_id=maths.id, school_class_id=jss1a.school_class_id,
                   question_type=QuestionType.THEORY, prompt="Explain the difference between a rational and an irrational number.",
                   marks=Decimal("5"), marking_guide="Should mention that rational numbers can be written as a fraction of integers; irrational cannot.")
    db.session.add(q2)

    # --- Attendance: last 3 school days for JSS 1A ---
    for days_ago in range(1, 4):
        d = date.today() - timedelta(days=days_ago)
        for s in jss1a_students:
            status = AttendanceStatus.ABSENT if (s.full_name == "Fatima Sani" and days_ago == 2) else AttendanceStatus.PRESENT
            db.session.add(StudentAttendance(
                student_id=s.id, class_arm_id=jss1a.id, date=d, status=status, recorded_by_id=teacher1.user_id
            ))
        for staff in [admin, accountant, teacher1, teacher2]:
            db.session.add(StaffAttendance(staff_id=staff.id, date=d, status=AttendanceStatus.PRESENT))

    db.session.commit()

    print("Demo data seeded:")
    print("  Admin      -> phone 08011110001 | password: Demo123!")
    print("  Accountant -> phone 08011110002 | password: Demo123!")
    print("  Teacher    -> phone 08011110003 | password: Demo123!  (Funmilayo Okoro, Mathematics/JSS1A)")
    print("  Teacher    -> phone 08011110004 | password: Demo123!  (David Eze, English/JSS1A)")
    print("  Parent     -> phone 08022220001 | password: Demo123!  (Mrs. Bello, guardian of Aisha Bello)")
    print("  Student    -> admission STU/2026/0001 | password: Student123!  (Aisha Bello)")
    print("  One voided payment is pre-loaded on the Reconciliation page for the demo.")
