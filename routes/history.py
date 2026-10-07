from flask import Blueprint, abort, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from extensions import db
from models import TroubleshootingSession
from services import decision_tree_service as tree
from services import device_service
from services import troubleshooting_service as store

history_bp = Blueprint("history", __name__, url_prefix="/dashboard")

STATUS_LABELS = {
    "ACTIVE": "In progress",
    "RESOLVED": "Resolved",
    "ESCALATED": "Professional help recommended",
    "UNRESOLVED": "Not finished",
}


def _own_or_404(session_id):
    row = db.session.get(TroubleshootingSession, session_id)
    if row is None or row.user_id != current_user.id:
        abort(404)
    return row


@history_bp.route("")
@login_required
def index():
    return redirect(url_for("history.list_sessions"))


@history_bp.route("/history")
@login_required
def list_sessions():
    rows = (
        TroubleshootingSession.query.filter_by(user_id=current_user.id)
        .order_by(TroubleshootingSession.created_at.desc())
        .all()
    )
    return render_template(
        "dashboard/history.html",
        rows=rows,
        status_labels=STATUS_LABELS,
        category_labels=tree.CATEGORY_LABELS,
    )


@history_bp.route("/session/<int:session_id>")
@login_required
def detail(session_id):
    row = _own_or_404(session_id)
    return render_template(
        "dashboard/session.html",
        row=row,
        node=tree.get_node(row.current_node),
        timeline=row.timeline(),
        status_labels=STATUS_LABELS,
        category_label=tree.CATEGORY_LABELS.get(row.category, row.category),
        device=device_service.summary(device_service.snapshot_for(row.id)),
    )


@history_bp.route("/session/<int:session_id>/resume")
@login_required
def resume(session_id):
    row = _own_or_404(session_id)
    if row.status != "ACTIVE":
        return redirect(url_for("history.detail", session_id=row.id))
    session["ts"] = store.to_ts(row)
    return redirect(url_for("troubleshoot.interview"))