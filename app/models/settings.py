from datetime import datetime
from app.extensions import db


class SchoolSettings(db.Model):
    """Singleton row (id is always 1) holding whole-school configuration
    that doesn't belong to any one module. Currently just the campus
    location used to verify staff check-ins."""

    __tablename__ = "school_settings"

    id = db.Column(db.Integer, primary_key=True)

    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    checkin_radius_m = db.Column(db.Integer, default=150)
    enforce_checkin_location = db.Column(db.Boolean, default=False)

    # Punctuality. Staff who check in after late_cutoff_time (read in the
    # school's own timezone) are flagged late. None means lateness isn't
    # tracked at all.
    timezone = db.Column(db.String(50), default="Africa/Lagos")
    late_cutoff_time = db.Column(db.Time, nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls):
        settings = cls.query.get(1)
        if not settings:
            settings = cls(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings

    @property
    def tracks_lateness(self):
        return self.late_cutoff_time is not None

    @property
    def is_configured(self):
        return self.latitude is not None and self.longitude is not None
