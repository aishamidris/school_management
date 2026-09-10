from app.extensions import db


class Permission(db.Model):
    """One row = 'role X is/isn't allowed to do capability Y'.

    Owner is never stored here — the owner always has every capability,
    enforced in code (see has_permission), so an owner can never
    accidentally lock themselves out of their own system.
    """
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    capability = db.Column(db.String(60), nullable=False)
    allowed = db.Column(db.Boolean, default=False, nullable=False)

    __table_args__ = (db.UniqueConstraint("role", "capability", name="uq_role_capability"),)
