"""staff punctuality (late flag), leave requests, duty assignments

Adds:
  * school_settings.timezone, school_settings.late_cutoff_time
  * staff_attendance.is_late, staff_attendance.minutes_late
  * tables: leave_requests, duties, duty_assignments
  * default permission rows for leave.manage / duties.view / duties.manage

Written to be safe to run on a database that already has some of this —
for example one where `python seed.py` (db.create_all) ran against the new
models before `flask db upgrade` — so every step checks first.

Revision ID: b7c2d91e4a35
Revises: ec4136529f9c
Create Date: 2026-10-01 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c2d91e4a35'
down_revision = 'ec4136529f9c'
branch_labels = None
depends_on = None


NEW_PERMISSIONS = {
    # role: {capability: allowed}
    "admin": {"leave.manage": True, "duties.view": True, "duties.manage": False},
    "accountant": {"leave.manage": False, "duties.view": False, "duties.manage": False},
    "teacher": {"leave.manage": False, "duties.view": False, "duties.manage": False},
}


def _columns(inspector, table):
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # ---- school_settings: timezone + late cut-off
    cols = _columns(inspector, "school_settings")
    with op.batch_alter_table("school_settings", schema=None) as batch_op:
        if "timezone" not in cols:
            batch_op.add_column(sa.Column("timezone", sa.String(length=50), nullable=True, server_default="Africa/Lagos"))
        if "late_cutoff_time" not in cols:
            batch_op.add_column(sa.Column("late_cutoff_time", sa.Time(), nullable=True))

    # ---- staff_attendance: late flag
    cols = _columns(inspector, "staff_attendance")
    with op.batch_alter_table("staff_attendance", schema=None) as batch_op:
        if "is_late" not in cols:
            batch_op.add_column(sa.Column("is_late", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "minutes_late" not in cols:
            batch_op.add_column(sa.Column("minutes_late", sa.Integer(), nullable=False, server_default="0"))

    # ---- leave_requests
    if "leave_requests" not in tables:
        op.create_table(
            "leave_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("staff_id", sa.Integer(), nullable=False),
            sa.Column("leave_type", sa.String(length=20), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=12), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("decided_by_id", sa.Integer(), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("admin_note", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["staff_id"], ["staff.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("leave_requests", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_leave_requests_staff_id"), ["staff_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_leave_requests_start_date"), ["start_date"], unique=False)
            batch_op.create_index(batch_op.f("ix_leave_requests_status"), ["status"], unique=False)

    # ---- duties
    if "duties" not in tables:
        op.create_table(
            "duties",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("location", sa.String(length=100), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("title"),
        )

    # ---- duty_assignments
    if "duty_assignments" not in tables:
        op.create_table(
            "duty_assignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("duty_id", sa.Integer(), nullable=False),
            sa.Column("staff_id", sa.Integer(), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=False),
            sa.Column("start_time", sa.Time(), nullable=True),
            sa.Column("end_time", sa.Time(), nullable=True),
            sa.Column("notes", sa.String(length=255), nullable=True),
            sa.Column("assigned_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["duty_id"], ["duties.id"]),
            sa.ForeignKeyConstraint(["staff_id"], ["staff.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("duty_assignments", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_duty_assignments_duty_id"), ["duty_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_duty_assignments_staff_id"), ["staff_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_duty_assignments_start_date"), ["start_date"], unique=False)

    # ---- default permission rows (so admins get leave review / roster view
    # without anyone having to re-run the seed script)
    if "permissions" in tables:
        existing = {
            (r[0], r[1])
            for r in bind.execute(sa.text("SELECT role, capability FROM permissions"))
        }
        for role, caps in NEW_PERMISSIONS.items():
            for capability, allowed in caps.items():
                if (role, capability) in existing:
                    continue
                bind.execute(
                    sa.text("INSERT INTO permissions (role, capability, allowed) VALUES (:r, :c, :a)"),
                    {"r": role, "c": capability, "a": allowed},
                )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "permissions" in tables:
        for caps in NEW_PERMISSIONS.values():
            for capability in caps:
                bind.execute(sa.text("DELETE FROM permissions WHERE capability = :c"), {"c": capability})

    for table in ("duty_assignments", "duties", "leave_requests"):
        if table in tables:
            op.drop_table(table)

    cols = _columns(inspector, "staff_attendance")
    with op.batch_alter_table("staff_attendance", schema=None) as batch_op:
        if "minutes_late" in cols:
            batch_op.drop_column("minutes_late")
        if "is_late" in cols:
            batch_op.drop_column("is_late")

    cols = _columns(inspector, "school_settings")
    with op.batch_alter_table("school_settings", schema=None) as batch_op:
        if "late_cutoff_time" in cols:
            batch_op.drop_column("late_cutoff_time")
        if "timezone" in cols:
            batch_op.drop_column("timezone")
