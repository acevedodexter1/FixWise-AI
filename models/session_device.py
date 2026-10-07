from datetime import datetime

from extensions import db


class SessionDevice(db.Model):
    """Which device a troubleshooting session was about.

    This is a separate table on purpose: the existing troubleshooting_sessions table is left
    untouched, so db.create_all() can add this on a database that already has data.
    The device facts are copied (snapshot) so editing or deleting the device later does not
    change an old report.
    """

    __tablename__ = "session_devices"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("troubleshooting_sessions.id"), nullable=False, unique=True
    )
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True)
    snapshot = db.Column(db.Text, nullable=False)  # JSON, see Device.snapshot()
    created_at = db.Column(db.DateTime, default=datetime.now)
