from flask import Blueprint, render_template

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    return render_template("home.html")


# Placeholder so the "Learn" link works. We'll replace it page by page.
@home_bp.route("/learn")
def learn():
    return render_template("placeholder.html", title="Learn troubleshooting")