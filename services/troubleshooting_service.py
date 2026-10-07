"""Saving troubleshooting sessions to the database (registered users only)."""
import json
from datetime import datetime

from flask import current_app

from extensions import db
from models import AIAnalysis, TroubleshootingAnswer, TroubleshootingSession, TroubleshootingStep
from services import decision_tree_service as tree
from services import safety_service


def create_session(user_id, problem, category, node):
    try:
        row = TroubleshootingSession(
            user_id=user_id, problem_description=problem, category=category, current_node=node
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not save the troubleshooting session")
        return None


def owned_by(db_id, user):
    if not user.is_authenticated:
        return False
    row = db.session.get(TroubleshootingSession, db_id)
    return row is not None and row.user_id == user.id


def record_progress(db_id, position, node, entry, next_node, category):
    """Save one answered question or step, then move the session to its next node."""
    try:
        row = db.session.get(TroubleshootingSession, db_id)
        if row is None or row.status != "ACTIVE":
            return
        if node["type"] == "question":
            db.session.add(TroubleshootingAnswer(
                session_id=row.id, position=position,
                question=entry["text"], answer=entry["answer"],
            ))
        else:
            db.session.add(TroubleshootingStep(
                session_id=row.id, step_number=position,
                instruction=node["title"], reason=node["why"],
                result=entry["answer"], completed=True,
            ))
        row.category = category
        row.current_node = next_node
        nxt = tree.get_node(next_node)
        if nxt["type"] == "resolved":
            row.status, row.final_result, row.completed_at = "RESOLVED", nxt["cause"], datetime.now()
        elif nxt["type"] == "escalate":
            row.status, row.final_result, row.completed_at = "ESCALATED", nxt["reason"], datetime.now()
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not save troubleshooting progress")


def mark_abandoned(db_id):
    """The user started over before finishing."""
    try:
        row = db.session.get(TroubleshootingSession, db_id)
        if row is not None and row.status == "ACTIVE":
            row.status, row.completed_at = "UNRESOLVED", datetime.now()
            db.session.commit()
    except Exception:
        db.session.rollback()


def to_ts(row):
    """Rebuild the browser-session state so an unfinished session can continue."""
    return {
        "problem": row.problem_description,
        "category": row.category,
        "node": row.current_node,
        "history": [{"text": i["text"], "answer": i["answer"]} for i in row.timeline()],
        "db_id": row.id,
        "analysis": load_analysis(row.id),
    }


def load_analysis(db_id):
    """The saved understanding of the problem, shaped like the one kept in the browser session."""
    row = (
        AIAnalysis.query.filter_by(session_id=db_id)
        .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc())
        .first()
    )
    if row is None:
        return None
    try:
        symptoms = json.loads(row.symptoms or "[]")
        causes = json.loads(row.possible_causes or "[]")
    except ValueError:
        symptoms, causes = [], []
    return {
        "summary": row.summary or "",
        "symptoms": symptoms,
        "possible_causes": causes,
        "warning": safety_service.WARNING,
        "source": row.source,
    }


def save_analysis(db_id, analysis):
    try:
        db.session.add(AIAnalysis(
            session_id=db_id,
            category=analysis["category"],
            summary=analysis["summary"],
            symptoms=json.dumps(analysis["symptoms"]),
            possible_causes=json.dumps(analysis["possible_causes"]),
            source=analysis["source"],
            ai_response=analysis.get("raw", ""),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not save the AI analysis")


def mark_escalated(db_id, node_id):
    """The request was referred to a professional before any step was tried."""
    try:
        row = db.session.get(TroubleshootingSession, db_id)
        if row is not None and row.status == "ACTIVE":
            row.status, row.final_result, row.completed_at = (
                "ESCALATED", tree.get_node(node_id)["reason"], datetime.now(),
            )
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not mark the session as escalated")