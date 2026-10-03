from datetime import datetime

from extensions import db


class TroubleshootingAnswer(db.Model):
    __tablename__ = "troubleshooting_answers"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("troubleshooting_sessions.id"), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)  # position in the whole interview
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)