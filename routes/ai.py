"""Screenshot analyzer page: upload a picture of an error (or type the message) and get a clear problem."""
from flask import Blueprint, current_app, flash, make_response, render_template, request, session
from flask_login import current_user

from services import decision_tree_service as tree
from services import device_service, screenshot_service

ai_bp = Blueprint("ai", __name__, url_prefix="/troubleshoot")


def _devices():
    return device_service.list_for(current_user.id) if current_user.is_authenticated else []


def _page(result=None):
    html = render_template(
        "troubleshoot/screenshot.html",
        result=result,
        devices=_devices(),
        ai_enabled=bool(current_app.config.get("AI_API_KEY")),
    )
    response = make_response(html)
    response.headers["Cache-Control"] = "no-store"  # the page can show text read from a private screenshot
    return response


@ai_bp.route("/screenshot", methods=["GET", "POST"])
def screenshot():
    if request.method == "GET":
        return _page()

    typed = request.form.get("error_text", "").strip()
    upload = request.files.get("screenshot")
    image = None
    if upload and upload.filename:
        data = upload.read()
        mime = screenshot_service.sniff_image(data)
        if not data:
            flash("That file is empty. Choose a screenshot and try again.", "error")
            return _page()
        if mime is None:
            flash("Upload a PNG, JPG or WebP screenshot.", "error")
            return _page()
        image = (mime, data)

    if not image and not typed:
        flash("Upload a screenshot or type the error message.", "error")
        return _page()

    made = session.get("shots_made", 0)
    categories = {k: v for k, v in tree.CATEGORY_LABELS.items() if k != "unknown"}
    result = screenshot_service.analyze(
        image, typed, categories, allow_ai=made < screenshot_service.MAX_AI_SCREENSHOTS_PER_VISIT
    )
    if result["ai_called"]:
        session["shots_made"] = made + 1
    return _page(result)
