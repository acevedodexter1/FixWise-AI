"""Numbers and listings for the admin dashboard. Everything here only reads."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import current_app
from sqlalchemy import func

from extensions import db
from models import AIAnalysis, AILesson, Device, TroubleshootingSession, User
from services import decision_tree_service as tree
from services import knowledge_service

STATUSES = ("RESOLVED", "ESCALATED", "ACTIVE", "UNRESOLVED")
STATUS_LABELS = {
    "ACTIVE": "In progress",
    "RESOLVED": "Resolved",
    "ESCALATED": "Professional help recommended",
    "UNRESOLVED": "Not finished",
}
PAGE_SIZE = 25


def _count(query):
    return query.scalar() or 0


def overview(days=7):
    since = datetime.now() - timedelta(days=days)
    by_status = dict(
        db.session.query(TroubleshootingSession.status, func.count()).group_by(TroubleshootingSession.status).all()
    )
    by_status = {status: by_status.get(status, 0) for status in STATUSES}
    finished = by_status["RESOLVED"] + by_status["ESCALATED"]

    by_category = (
        db.session.query(TroubleshootingSession.category, func.count())
        .group_by(TroubleshootingSession.category)
        .order_by(func.count().desc())
        .all()
    )
    sources = dict(db.session.query(AIAnalysis.source, func.count()).group_by(AIAnalysis.source).all())

    return {
        "days": days,
        "users": _count(db.session.query(func.count(User.id))),
        "admins": _count(db.session.query(func.count(User.id)).filter(User.role == "ADMIN")),
        "new_users": _count(db.session.query(func.count(User.id)).filter(User.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days))),
        "devices": _count(db.session.query(func.count(Device.id))),
        "sessions": sum(by_status.values()),
        "recent_sessions": _count(
            db.session.query(func.count(TroubleshootingSession.id)).filter(TroubleshootingSession.created_at >= since)
        ),
        "by_status": [(s, STATUS_LABELS[s], by_status[s]) for s in STATUSES],
        # share of FINISHED sessions that were solved; unfinished ones say nothing about success
        "resolved_rate": round(by_status["RESOLVED"] / finished * 100) if finished else None,
        "by_category": [
            {"key": key, "label": tree.CATEGORY_LABELS.get(key, key), "count": count}
            for key, count in by_category
        ],
        "ai_analyses": sources.get("ai", 0),
        "keyword_analyses": sources.get("keywords", 0),
        "lessons": _count(db.session.query(func.count(AILesson.id))),
    }


def users_page(page):
    counts = dict(
        db.session.query(TroubleshootingSession.user_id, func.count(TroubleshootingSession.id))
        .filter(TroubleshootingSession.user_id.isnot(None))
        .group_by(TroubleshootingSession.user_id)
        .all()
    )
    pagination = User.query.order_by(User.created_at.desc(), User.id.desc()).paginate(
        page=page, per_page=PAGE_SIZE, error_out=False
    )
    return pagination, counts


def sessions_page(page, status=None, category=None):
    """Saved sessions, newest first. Unknown filter values are ignored rather than trusted."""
    query = db.session.query(TroubleshootingSession, User).outerjoin(User, User.id == TroubleshootingSession.user_id)
    if status in STATUSES:
        query = query.filter(TroubleshootingSession.status == status)
    if category in tree.CATEGORY_LABELS:
        query = query.filter(TroubleshootingSession.category == category)
    return query.order_by(TroubleshootingSession.created_at.desc(), TroubleshootingSession.id.desc()).paginate(
        page=page, per_page=PAGE_SIZE, error_out=False
    )


# ---------- knowledge base (read-only) ----------

def knowledge_summary():
    """One row per troubleshooting category, with counts of each kind of node."""
    rows = {}
    for node_id, node in tree.TREE.items():
        key = tree.category_of(node_id)
        if key is None:
            continue
        row = rows.setdefault(key, {"question": 0, "step": 0, "resolved": 0, "escalate": 0})
        row[node["type"]] += 1
    cases = {}
    for case in knowledge_service.ERROR_CASES:
        cases[case["category"]] = cases.get(case["category"], 0) + 1
    result = []
    for key, label in tree.CATEGORY_LABELS.items():
        if key not in rows:
            continue
        counts = rows[key]
        result.append({
            "key": key,
            "label": label,
            "keywords": tree.KEYWORDS.get(key, []),
            "nodes": sum(counts.values()),
            "counts": counts,
            "longest_path": tree.steps_remaining(tree.START_NODES[key]),
            "error_cases": cases.get(key, 0),
        })
    return result


def _node_text(node):
    return node.get("text") or node.get("title") or node.get("cause") or node.get("reason") or ""


def _links(node):
    if node["type"] == "question":
        return [(option["label"], option["next"]) for option in node["options"]]
    if node["type"] == "step":
        return [("Fixed", node["fixed"]), ("Not fixed", node["not_fixed"])]
    return []


def outline(category):
    """The category's nodes in reading order (depth first from its start node), or None."""
    if category not in tree.START_NODES or category == "unknown":
        return None
    order, seen, stack = [], set(), [tree.START_NODES[category]]
    while stack:
        node_id = stack.pop()
        if node_id in seen or tree.category_of(node_id) != category:
            continue
        seen.add(node_id)
        node = tree.TREE[node_id]
        order.append({"id": node_id, "type": node["type"], "text": _node_text(node), "links": _links(node)})
        stack.extend(reversed([target for _, target in _links(node)]))
    return order


def error_cases():
    return [
        {**knowledge_service.public(case), "category_label": tree.CATEGORY_LABELS[case["category"]]}
        for case in knowledge_service.ERROR_CASES
    ]


# ---------- AI settings (read-only, never shows the key) ----------

def ai_settings():
    cfg = current_app.config
    host = urlparse(cfg.get("AI_BASE_URL") or "").hostname or ""
    return {
        "enabled": bool(cfg.get("AI_API_KEY")),
        "provider_host": host or "default (OpenAI)",
        "model": cfg.get("AI_MODEL") or "not set",
        "vision_model": cfg.get("AI_VISION_MODEL") or "",
        "uses_model_for_images": not cfg.get("AI_VISION_MODEL"),
    }
