from datetime import datetime

from extensions import db


class Device(db.Model):
    """A computer the user owns, saved once so it can be attached to troubleshooting sessions."""

    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)  # the user's nickname, e.g. "School laptop"
    device_type = db.Column(db.String(20), nullable=False, default="Laptop")
    brand = db.Column(db.String(60))
    model = db.Column(db.String(80))
    os = db.Column(db.String(30))
    notes = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    user = db.relationship("User", backref=db.backref("devices", lazy="dynamic"))

    def snapshot(self):
        """The facts a technician needs, copied so later edits never rewrite an old report."""
        return {
            "name": self.name,
            "type": self.device_type,
            "brand": self.brand or "",
            "model": self.model or "",
            "os": self.os or "",
            "notes": self.notes or "",
        }
