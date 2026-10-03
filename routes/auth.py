from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from extensions import db
from forms import LoginForm, RegisterForm
from models.user import User

auth_bp = Blueprint("auth", __name__)


def _safe_next(target):
    # Only allow paths on this site (prevents redirecting users to other websites)
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("home.home")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            form.email.errors = list(form.email.errors) + ["That email is already registered."]
        else:
            user = User(name=form.name.data.strip(), email=email)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f"Welcome, {user.name}! Your account is ready.", "ok")
            return redirect(url_for("home.home"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home.home"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(_safe_next(request.args.get("next")))
        flash("Wrong email or password.", "error")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "ok")
    return redirect(url_for("home.home"))