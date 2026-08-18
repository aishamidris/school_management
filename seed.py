"""Run once to set up the first owner account and a starting academic session.

Usage:
    python seed.py
"""
from app import create_app
from app.extensions import db
from app.models.user import User, Role
from app.models.academic import AcademicSession, Term

app = create_app()

with app.app_context():
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
        db.session.flush()  # get session.id before commit

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
    print("Seed complete.")
