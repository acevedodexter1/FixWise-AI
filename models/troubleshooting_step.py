from datetime import datetime

from extensions import db


class TroubleshootingStep(db.Model):
    __tablename__ = "troubleshooting_steps"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("troubleshooting_sessions.id"), nullable=False, index=True)
    step_number = db.Column(db.Integer, nullable=False)  # position in the whole interview
    instruction = db.Column(db.Text, nullable=False)
    reason = db.Column(db.Text)
    result = db.Column(db.String(100))
    completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)