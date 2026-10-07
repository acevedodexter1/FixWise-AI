from datetime import datetime

from extensions import db


class AIAnalysis(db.Model):
    __tablename__ = "ai_analyses"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("troubleshooting_sessions.id"), nullable=False, index=True)
    category = db.Column(db.String(30))
    summary = db.Column(db.Text)
    symptoms = db.Column(db.Text)  # JSON list
    possible_causes = db.Column(db.Text)  # JSON list
    source = db.Column(db.String(10))  # "ai" or "keywords"
    ai_response = db.Column(db.Text)  # raw AI reply, for review
    created_at = db.Column(db.DateTime, default=datetime.now)