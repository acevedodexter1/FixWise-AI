"""Device profiles: saving a user's computers and attaching one to a troubleshooting session."""
import json

from flask import current_app

from extensions import db
from models import Device, SessionDevice

DEVICE_TYPES = ("Laptop", "Desktop", "All-in-one", "Other")
OPERATING_SYSTEMS = ("Windows 11", "Windows 10", "Windows 8.1 or older", "macOS", "Linux", "Other")


def list_for(user_id):
    return Device.query.filter_by(user_id=user_id).order_by(Device.name).all()


def get_owned(device_id, user_id):
    """The device, only if it belongs to this user. Anything else is None."""
    device = db.session.get(Device, device_id)
    return device if device is not None and device.user_id == user_id else None


def summary(snapshot):
    """One readable line, e.g. 'School laptop: Laptop, Acer Aspire 5, Windows 11'."""
    if not snapshot:
        return ""
    details = [
        snapshot.get("type"),
        " ".join(part for part in (snapshot.get("brand"), snapshot.get("model")) if part),
        snapshot.get("os"),
    ]
    details = ", ".join(part for part in details if part)
    name = snapshot.get("name") or ""
    return f"{name}: {details}" if name and details else name or details


def attach(session_id, device):
    """Link a device to a session by copying its facts. Never raises: a failure must not stop troubleshooting."""
    try:
        db.session.add(SessionDevice(
            session_id=session_id, device_id=device.id, snapshot=json.dumps(device.snapshot()),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not attach the device to the session")


def snapshot_for(session_id):
    """The device facts saved with a session, or None if no device was chosen."""
    if not session_id:
        return None
    row = SessionDevice.query.filter_by(session_id=session_id).first()
    if row is None:
        return None
    try:
        return json.loads(row.snapshot)
    except ValueError:
        return None
