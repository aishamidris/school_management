"""
Granular permission system.

Roles (User.role) still gate the big buckets — a parent can never reach
staff-only pages no matter what, and an accountant can never reach the
reconciliation panel regardless of settings (that exclusion is a
structural security guarantee, not a preference). But *within* the
staff roles the owner decides exactly what each role can see and do,
rather than the role alone silently deciding it.

How it works:
- PERMISSIONS is the full catalog of togglable capabilities.
- DEFAULT_PERMISSIONS is what a role starts with — seeded as explicit
  rows in the Permission table by seed.py, so every (role, capability)
  pair always has an explicit True/False rather than relying on a
  fallback at check-time.
- has_permission(user, key) reads the Permission table. Owner always
  passes, every other role needs an explicit "allowed" row.
- The owner edits this from Settings -> Permissions: one checkbox grid,
  rows = capabilities, columns = Admin / Accountant / Teacher.
"""

from app.models.user import Role

# key -> (human label, module group)
PERMISSIONS = {
    "students.view": ("View student records", "Students"),
    "students.manage": ("Register & edit students, change status", "Students"),
    "staff.view": ("View staff records", "Staff"),
    "staff.manage": ("Register & edit staff, reset passwords, activate/deactivate", "Staff"),
    "fees.view": ("View fee structures, invoices & receipts", "Fees"),
    "fees.manage": ("Create fee structures & generate invoices", "Fees"),
    "payments.record": ("Record student payments", "Fees"),
    "payments.void": ("Void a recorded payment", "Fees"),
    "results.view": ("View results & class broadsheets", "Results"),
    "results.enter": ("Enter / edit student results", "Results"),
    "results.setup": ("Manage grading scale & subject-to-class assignments", "Results"),
    "exams.manage": ("Create exams, paste/add questions, print papers", "Exams"),
    "reconciliation.view": ("View the financial reconciliation dashboard", "Oversight"),
    "dashboard.owner_view": ("See owner-level figures on the dashboard", "Oversight"),
    "attendance.student.view": ("View student attendance records", "Attendance"),
    "attendance.student.mark": ("Mark daily student attendance", "Attendance"),
    "attendance.staff.view": ("View staff attendance records", "Attendance"),
    "attendance.staff.mark": ("Mark daily staff attendance", "Attendance"),
    "audit.view": ("View the full audit log", "Oversight"),
}

# Roles the owner can actually configure. Owner is always all-access;
# parent/student see only their own linked records, which isn't a
# capability toggle — it's built into what those pages query.
CONFIGURABLE_ROLES = [Role.ADMIN, Role.ACCOUNTANT, Role.TEACHER]

DEFAULT_PERMISSIONS = {
    Role.ADMIN: {
        "students.view", "students.manage",
        "staff.view", "staff.manage",
        "fees.view", "fees.manage", "payments.record", "payments.void",
        "results.view", "results.enter", "results.setup",
        "exams.manage",
        "reconciliation.view", "dashboard.owner_view",
        "attendance.student.view", "attendance.student.mark",
        "attendance.staff.view", "attendance.staff.mark",
        "audit.view",
    },
    Role.ACCOUNTANT: {
        "students.view",
        "fees.view", "payments.record",
    },
    Role.TEACHER: {
        "students.view",
        "results.view", "results.enter",
        "exams.manage",
        "attendance.student.view", "attendance.student.mark",
    },
}

# Pairs that are hard-coded exclusions elsewhere in the route decorators
# (roles_required, not permission_required) — the owner can't grant these
# no matter what, because they're structural security guarantees, not
# preferences. The permissions UI disables these checkboxes and the
# manage() route skips them entirely so a page save never overwrites them.
STRUCTURALLY_RESTRICTED = {
    (Role.ACCOUNTANT, "staff.view"),
    (Role.ACCOUNTANT, "staff.manage"),
    (Role.ACCOUNTANT, "reconciliation.view"),
    (Role.ACCOUNTANT, "payments.void"),
    (Role.ACCOUNTANT, "dashboard.owner_view"),
    (Role.ACCOUNTANT, "attendance.student.view"),
    (Role.ACCOUNTANT, "attendance.student.mark"),
    (Role.ACCOUNTANT, "attendance.staff.view"),
    (Role.ACCOUNTANT, "attendance.staff.mark"),
    (Role.ACCOUNTANT, "audit.view"),
    (Role.TEACHER, "attendance.staff.view"),
    (Role.TEACHER, "attendance.staff.mark"),
    (Role.TEACHER, "audit.view"),
}


def has_permission(user, key):
    """Owner always passes. Every other role needs an explicit
    'allowed' row in the Permission table for (role, key)."""
    if not user or not user.is_authenticated:
        return False
    if user.role == Role.OWNER:
        return True
    from app.models.permission import Permission
    return Permission.query.filter_by(role=user.role, capability=key, allowed=True).first() is not None
