"""Admin dashboard. Read-only; admins are made with `python make_admin.py <email>`."""
from functools import wraps

from flask import Blueprint, abort, make_response, render_template, request
from flask_login import current_user, login_required

from services import admin_service
from services import decision_tree_service as tree

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(404)  # not 403: do not advertise that an admin area exists
        return view(*args, **kwargs)

    return login_required(wrapped)


def _page_number():
    return max(request.args.get("page", 1, type=int) or 1, 1)


def _private(html):
    response = make_response(html)
    response.headers["Cache-Control"] = "no-store"  # these pages list other people's problems and emails
    return response


@admin_bp.route("")
@admin_required
def dashboard():
    return _private(render_template("admin/dashboard.html", stats=admin_service.overview()))


@admin_bp.route("/users")
@admin_required
def users():
    pagination, counts = admin_service.users_page(_page_number())
    return _private(render_template("admin/users.html", pagination=pagination, counts=counts))


@admin_bp.route("/sessions")
@admin_required
def sessions():
    status = request.args.get("status", "")
    category = request.args.get("category", "")
    pagination = admin_service.sessions_page(_page_number(), status, category)
    return _private(render_template(
        "admin/reports.html",
        pagination=pagination,
        status=status,
        category=category,
        statuses=admin_service.STATUS_LABELS,
        categories={k: v for k, v in tree.CATEGORY_LABELS.items()},
    ))


@admin_bp.route("/knowledge")
@admin_required
def knowledge():
    return _private(render_template("admin/categories.html", rows=admin_service.knowledge_summary()))


@admin_bp.route("/knowledge/<category>")
@admin_required
def decision_tree(category):
    nodes = admin_service.outline(category)
    if nodes is None:
        abort(404)
    return _private(render_template(
        "admin/decision_trees.html", category=category, label=tree.CATEGORY_LABELS[category], nodes=nodes,
    ))


@admin_bp.route("/error-cases")
@admin_required
def error_cases():
    return _private(render_template("admin/error_cases.html", cases=admin_service.error_cases()))


@admin_bp.route("/ai")
@admin_required
def ai_settings():
    return _private(render_template(
        "admin/ai_settings.html", ai=admin_service.ai_settings(), stats=admin_service.overview(),
    ))
