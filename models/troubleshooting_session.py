from datetime import datetime

from extensions import db


class TroubleshootingSession(db.Model):
    __tablename__ = "troubleshooting_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    problem_description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(30), nullable=False, default="unknown")
    current_node = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(12), nullable=False, default="ACTIVE")  # ACTIVE, RESOLVED, ESCALATED, UNRESOLVED
    final_result = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("troubleshooting_sessions", lazy="dynamic"))
    steps = db.relationship(
        "TroubleshootingStep", backref="session",
        order_by="TroubleshootingStep.step_number", cascade="all, delete-orphan",
    )
    answers = db.relationship(
        "TroubleshootingAnswer", backref="session",
        order_by="TroubleshootingAnswer.position", cascade="all, delete-orphan",
    )

    def timeline(self):
        """Questions and steps merged in the order they happened."""
        items = [{"position": a.position, "text": a.question, "answer": a.answer} for a in self.answers]
        items += [{"position": s.step_number, "text": s.instruction, "answer": s.result} for s in self.steps]
        return sorted(items, key=lambda item: item["position"])