"""Run once to set up the database.

Usage:
    python seed.py            # base data only (owner, classes, grading, permissions)
    python seed.py --demo     # base data PLUS a full realistic demo dataset
                               # (sample students, staff, fees, payments,
                               # results, an exam, attendance) — useful for
                               # showing the app to a prospective school.
"""
import sys
from app import create_app
from app.seeding.base_seed import seed_base_data
from app.seeding.demo_seed import seed_demo_data

app = create_app()

with app.app_context():
    seed_base_data()

    if "--demo" in sys.argv:
        seed_demo_data()

    print("Seed complete.")
