from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_login import current_user

from services import decision_tree_service as tree
from services import troubleshooting_service as store

troubleshoot_bp = Blueprint("troubleshoot", __name__, url_prefix="/troubleshoot")


def _back_home():
    return redirect(url_for("home.home"))


def _get_ts():
    """Current interview from the browser session. Drops the database link if it isn't this user's."""
    ts = session.get("ts")
    if ts and ts.get("db_id") and not store.owned_by(ts["db_id"], current_user):
        ts["db_id"] = None
        session["ts"] = ts
    return ts


@troubleshoot_bp.route("", methods=["GET", "POST"])
def start():
    if request.method == "POST":
        problem = request.form.get("problem", "").strip()
        if not problem:
            return _back_home()

        old = session.get("ts")
        if old and old.get("db_id") and store.owned_by(old["db_id"], current_user):
            store.mark_abandoned(old["db_id"])

        category = tree.detect_category(problem)
        node = tree.START_NODES[category]
        db_id = None
        if current_user.is_authenticated:  # guests are not saved
            db_id = store.create_session(current_user.id, problem, category, node)
        session["ts"] = {
            "problem": problem,
            "category": category,
            "node": node,
            "history": [],
            "db_id": db_id,
        }
        return redirect(url_for("troubleshoot.interview"))
    if "ts" in session:
        return redirect(url_for("troubleshoot.interview"))
    return _back_home()


@troubleshoot_bp.route("/interview")
def interview():
    ts = _get_ts()
    if not ts:
        return _back_home()
    node = tree.get_node(ts["node"])
    done = len(ts["history"])
    total = done + tree.steps_remaining(ts["node"])
    percent = int(done / total * 100) if total else 100
    return render_template(
        "troubleshoot/interview.html",
        ts=ts,
        node=node,
        done=done,
        total=total,
        percent=percent,
        category_label=tree.CATEGORY_LABELS.get(ts["category"], ""),
    )


@troubleshoot_bp.route("/answer", methods=["POST"])
def answer():
    ts = _get_ts()
    if not ts:
        return _back_home()
    node = tree.get_node(ts["node"])
    choice = request.form.get("choice", "")
    history = ts["history"]
    position = len(history) + 1

    if node["type"] == "question":
        try:
            option = node["options"][int(choice)]
        except (ValueError, IndexError):
            return redirect(url_for("troubleshoot.interview"))
        entry = {"text": node["text"], "answer": option["label"]}
        next_node = option["next"]
    elif node["type"] == "step":
        if choice == "fixed":
            result, next_node = node.get("fixed_label", "It worked"), node["fixed"]
        elif choice == "not_fixed":
            result, next_node = node.get("not_fixed_label", "Still not working"), node["not_fixed"]
        elif choice == "tried":
            # "I already tried this": record it and move on without repeating the step
            result, next_node = "Already tried (skipped)", node["not_fixed"]
        else:
            return redirect(url_for("troubleshoot.interview"))
        entry = {"text": node["title"], "answer": result}
    else:
        return redirect(url_for("troubleshoot.interview"))

    history.append(entry)
    ts["history"] = history
    ts["node"] = next_node
    ts["category"] = tree.category_of(next_node) or ts["category"]
    session["ts"] = ts

    if ts.get("db_id"):
        store.record_progress(ts["db_id"], position, node, entry, next_node, ts["category"])
    return redirect(url_for("troubleshoot.interview"))


@troubleshoot_bp.route("/restart")
def restart():
    ts = session.pop("ts", None)
    if ts and ts.get("db_id") and store.owned_by(ts["db_id"], current_user):
        store.mark_abandoned(ts["db_id"])
    return _back_home()