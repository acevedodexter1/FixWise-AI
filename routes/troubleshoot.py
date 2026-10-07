from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_login import current_user

from services import decision_tree_service as tree
from services import troubleshooting_service as store
from services import ai_service
from services import device_service
from services import knowledge_service
from services import learning_service as learning
from services import safety_service
from services import symptom_service

troubleshoot_bp = Blueprint("troubleshoot", __name__, url_prefix="/troubleshoot")
DEVICE_KINDS = {"laptop": "Laptop", "desktop": "Desktop PC"}  # the home page device cards


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

        device = None  # only signed-in users have devices, and only their own can be chosen
        device_id = request.form.get("device_id", "")
        if current_user.is_authenticated and device_id.isdigit():
            device = device_service.get_owned(int(device_id), current_user.id)

        old = session.get("ts")
        if old and old.get("db_id") and store.owned_by(old["db_id"], current_user):
            store.mark_abandoned(old["db_id"])

        referral = safety_service.check_request(problem)  # hazards / repairs we never guide
        if referral:
            analysis = safety_service.empty_analysis("unknown")  # the AI is not called at all
            category, node = "unknown", referral
        else:
            categories = {k: v for k, v in tree.CATEGORY_LABELS.items() if k != "unknown"}
            analysis = ai_service.analyze_problem(problem, categories, fallback=symptom_service.detect_category)
            known = knowledge_service.match_error(problem)  # a curated error beats the AI's guess
            if known and not known.get("generic"):
                analysis["category"], analysis["category_confidence"] = known["category"], None
                analysis["low_confidence"] = False
            elif known and analysis["category"] == "unknown":
                analysis["category"] = known["category"]  # a vague message only fills a gap
            hint = request.form.get("category_hint", "")  # from the screenshot analyzer
            if analysis["category"] == "unknown" and hint in categories:
                analysis["category"] = hint  # only used when nothing else could tell
            category = analysis["category"] if analysis["category"] in tree.START_NODES else "unknown"
            node = tree.START_NODES[category]

        kind = request.form.get("device_kind", "")  # the device card the user tapped
        if kind in DEVICE_KINDS and analysis["device_type"] in ("unknown", "computer"):
            analysis["device_type"], analysis["device"] = "computer", DEVICE_KINDS[kind]

        db_id = None
        if current_user.is_authenticated:  # guests are not saved
            db_id = store.create_session(current_user.id, problem, category, node)
            if db_id and device:
                device_service.attach(db_id, device)
            if db_id and referral:
                store.mark_escalated(db_id, node)
            elif db_id:
                store.save_analysis(db_id, analysis)
        session["ts"] = {
            "problem": problem,
            "category": category,
            "node": node,
            "history": [],
            "db_id": db_id,
            "analysis": {
                k: analysis.get(k)
                for k in (
                    "summary", "symptoms", "possible_causes", "warning", "source",
                    "device", "device_type", "device_confidence", "category_confidence", "low_confidence",
                )
            },
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



@troubleshoot_bp.route("/teach", methods=["POST"])
def teach():
    ts = _get_ts()
    if not ts:
        return _back_home()
    node = tree.get_node(ts["node"])
    if node["type"] not in ("resolved", "escalate"):
        return redirect(url_for("troubleshoot.interview"))

    level = request.form.get("level", "beginner")
    if level not in learning.LEVELS:
        level = "beginner"

    made = session.get("lessons_made", 0)  # protects the free AI limit
    lesson, source = learning.get_lesson(
        ts.get("db_id"), level, ts["problem"], ts["history"], node,
        allow_ai=made < learning.MAX_AI_LESSONS_PER_VISIT,
    )
    if source == "ai":
        session["lessons_made"] = made + 1

    return render_template(
        "learning/teach_me.html",
        ts=ts, lesson=lesson, source=source, level=level,
        category_label=tree.CATEGORY_LABELS.get(ts["category"], ""),
    )