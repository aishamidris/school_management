# School Management App — Phase 1 Scaffold

Flask + SQLAlchemy + Bootstrap. This is the foundation: database models for
the core Phase 1 modules, role-based login, and dashboard routing per role.

## What's included

- **Models** (`app/models/`): User & audit log, academic structure
  (Session → Term → Class → Arm → Subject), students/parents/staff with
  proper status lifecycle, attendance, fees/invoices/payments/expenses,
  exams/questions/results, staff tasks, announcements.
- **Auth** (`app/blueprints/auth/`): login with lockout after 5 failed
  attempts, audit-logged login/logout.
- **Dashboard routing** (`app/blueprints/main/`): routes each role to its
  own dashboard. Owner/Admin dashboard already computes live stats
  (students, fees expected/collected/outstanding, collection rate).
- **Audit logging** (`app/utils/audit.py`): call `log_action(...)` anywhere
  you record a payment, edit a student, etc. This is what will power the
  accountant/owner reconciliation feature later.
- **Role guard** (`app/utils/decorators.py`): `@roles_required(Role.OWNER, Role.ADMIN)`
  to restrict routes.

## Setup

```bash
cd school_management
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then edit SECRET_KEY
python seed.py                # creates DB tables + first owner login + a sample term
python run.py
```

Visit `http://127.0.0.1:5000` and log in with:
- **Email:** owner@school.com
- **Password:** ChangeMe123!

(Change this password immediately — there's no "force password change on
first login" yet; that's a good next addition.)

## What's deliberately NOT built yet

This is the scaffold, not the finished app. Still missing (in rough
build order):

1. **Student/Staff/Parent CRUD** — forms and routes to actually create
   these records (currently only the models exist).
2. **Fee structure & invoice generation** — admin UI to set fees per
   class/term and auto-generate student invoices.
3. **Payment recording** — accountant UI, with every action wired
   through `log_action()`.
4. **Result entry** — teacher UI for CA/exam scores, auto grade
   calculation against `GradeBand`.
5. **Exam question builder + paste-import parser** — the paste-to-parse
   feature needs a text-parsing function that splits pasted MCQ/theory
   blocks into `Question`/`QuestionOption` rows.
6. **Reconciliation view** — compares invoice totals vs payment totals,
   flags discrepancies, drills into the audit log.
7. **Attendance UI** — daily marking screens for teachers/admin.
8. **Announcements & tasks UI**.

## Suggested order to keep building

Given what's already in place, the fastest path to something demoable is:

1. Student CRUD (admin) → so there's data to work with
2. Fee structure + invoice generation → so the dashboard numbers become real
3. Payment recording (accountant) → completes the financial loop
4. Result entry (teacher) → completes the academic loop
5. Reconciliation view → ties it together, this is your differentiator

Say the word and we'll build whichever of these you want next — student
CRUD is the natural next step since almost everything else depends on
having students in the system.
