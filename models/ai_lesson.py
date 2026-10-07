from datetime import datetime

from extensions import db


class AILesson(db.Model):
    __tablename__ = "ai_lessons"
    __table_args__ = (db.UniqueConstraint("session_id", "level", name="uq_lesson_session_level"),)

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("troubleshooting_sessions.id"), nullable=False, index=True)
    level = db.Column(db.String(10), nullable=False)  # "beginner" or "technical"
    content = db.Column(db.Text, nullable=False)  # the lesson as JSON
    created_at = db.Column(db.DateTime, default=datetime.now)