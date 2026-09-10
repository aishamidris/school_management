"""Base seed data every deployment needs: owner account, academic
session/terms, the full class list, grading scale, starter subjects,
and default role permissions.

This is intentionally idempotent — every block checks "does this already
exist?" before creating anything, so it's always safe to call again
(e.g. on every app boot in a free-tier deployment with no persistent
disk, or manually via `python seed.py`).
"""
from app.extensions import db
from app.models.user import User, Role
from app.models.academic import AcademicSession, Term, SchoolClass, ClassArm, Subject
from app.models.exam import GradeBand
from app.models.permission import Permission
from app.utils.permissions import PERMISSIONS, DEFAULT_PERMISSIONS, CONFIGURABLE_ROLES


def seed_base_data():
    """Call this from inside an active app context. Returns nothing —
    prints a short log of what it did, same as running seed.py directly."""
    db.create_all()

    if not User.query.filter_by(role=Role.OWNER).first():
        owner = User(
            role=Role.OWNER,
            full_name="School Owner",
            email="owner@school.com",
            phone="08000000000",
        )
        owner.set_password("ChangeMe123!")
        db.session.add(owner)
        print("Created owner account -> email: owner@school.com | password: ChangeMe123!")
    else:
        print("Owner account already exists, skipping.")

    if not AcademicSession.query.first():
        session = AcademicSession(name="2026/2027", is_current=True)
        db.session.add(session)
        db.session.flush()

        terms = [
            Term(session_id=session.id, name="First Term", is_current=True),
            Term(session_id=session.id, name="Second Term"),
            Term(session_id=session.id, name="Third Term"),
        ]
        db.session.add_all(terms)
        print("Created academic session 2026/2027 with three terms.")
    else:
        print("Academic session already exists, skipping.")

    db.session.commit()

    current_session = AcademicSession.query.filter_by(is_current=True).first()
    if not SchoolClass.query.first() and current_session:
        class_names = (
            [f"Nursery {i}" for i in range(1, 4)]
            + [f"Primary {i}" for i in range(1, 6)]
            + [f"JSS {i}" for i in range(1, 4)]
            + [f"SSS {i}" for i in range(1, 4)]
        )
        for i, name in enumerate(class_names):
            sc = SchoolClass(name=name, order=i)
            db.session.add(sc)
            db.session.flush()
            for arm_name in ["A", "B"]:
                db.session.add(ClassArm(school_class_id=sc.id, session_id=current_session.id, name=arm_name))
        print(f"Created {len(class_names)} classes (Nursery 1 - SSS 3) with arms A & B.")
    else:
        print("Classes already exist, skipping.")

    db.session.commit()

    if not GradeBand.query.first():
        default_bands = [
            (70, 100, "A", "Excellent"),
            (60, 69.99, "B", "Very Good"),
            (50, 59.99, "C", "Good"),
            (45, 49.99, "D", "Fair"),
            (40, 44.99, "E", "Pass"),
            (0, 39.99, "F", "Fail"),
        ]
        for min_s, max_s, grade, remark in default_bands:
            db.session.add(GradeBand(min_score=min_s, max_score=max_s, grade=grade, remark=remark))
        print("Created default grading scale (A-F).")
    else:
        print("Grade bands already exist, skipping.")

    if not Subject.query.first():
        for name in ["Mathematics", "English Language", "Basic Science", "Social Studies"]:
            db.session.add(Subject(name=name))
        print("Created sample subjects.")
    else:
        print("Subjects already exist, skipping.")

    existing_permission_pairs = {(p.role, p.capability) for p in Permission.query.all()}
    added = 0
    for role in CONFIGURABLE_ROLES:
        defaults = DEFAULT_PERMISSIONS.get(role, set())
        for key in PERMISSIONS:
            if (role, key) in existing_permission_pairs:
                continue
            db.session.add(Permission(role=role, capability=key, allowed=(key in defaults)))
            added += 1
    if added:
        print(f"Added {added} new permission row(s).")
    else:
        print("Permissions already fully configured, skipping.")

    db.session.commit()
    print("Base seed complete.")
