from flask import Blueprint, render_template
from flask_login import current_user

from services import device_service

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    devices = device_service.list_for(current_user.id) if current_user.is_authenticated else []
    return render_template("home.html", devices=devices)


# Placeholder so the "Learn" link works. We'll replace it page by page.
@home_bp.route("/learn")
def learn():
    return render_template("placeholder.html", title="Learn troubleshooting")