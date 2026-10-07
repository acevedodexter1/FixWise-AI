"""Device profiles: the computers a signed-in user has saved."""
from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from extensions import db
from forms import DeviceForm
from models import Device, SessionDevice
from services import device_service

devices_bp = Blueprint("devices", __name__, url_prefix="/dashboard/devices")

MAX_DEVICES = 10  # per user: plenty for a student, and stops a form being used to fill the database


def _own_or_404(device_id):
    device = device_service.get_owned(device_id, current_user.id)
    if device is None:
        abort(404)
    return device


def _save(device, form):
    device.name = form.name.data.strip()
    device.device_type = form.device_type.data
    device.brand = (form.brand.data or "").strip() or None
    device.model = (form.model.data or "").strip() or None
    device.os = form.os.data
    device.notes = (form.notes.data or "").strip() or None


@devices_bp.route("")
@login_required
def list_devices():
    return render_template(
        "dashboard/devices.html", devices=device_service.list_for(current_user.id), limit=MAX_DEVICES,
    )


@devices_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if Device.query.filter_by(user_id=current_user.id).count() >= MAX_DEVICES:
        flash(f"You can save up to {MAX_DEVICES} devices. Delete one to add another.", "error")
        return redirect(url_for("devices.list_devices"))
    form = DeviceForm()
    if form.validate_on_submit():
        device = Device(user_id=current_user.id)
        _save(device, form)
        db.session.add(device)
        db.session.commit()
        flash(f"Saved {device.name}.", "ok")
        return redirect(url_for("devices.list_devices"))
    return render_template("dashboard/add_device.html", form=form, device=None)


@devices_bp.route("/<int:device_id>/edit", methods=["GET", "POST"])
@login_required
def edit(device_id):
    device = _own_or_404(device_id)
    form = DeviceForm(obj=device)
    if form.validate_on_submit():
        _save(device, form)
        db.session.commit()
        flash(f"Updated {device.name}.", "ok")
        return redirect(url_for("devices.list_devices"))
    return render_template("dashboard/add_device.html", form=form, device=device)


@devices_bp.route("/<int:device_id>/delete", methods=["POST"])
@login_required
def delete(device_id):
    device = _own_or_404(device_id)
    name = device.name
    # Old reports keep their own copy of the device facts, so only the link is cleared.
    SessionDevice.query.filter_by(device_id=device.id).update({"device_id": None})
    db.session.delete(device)
    db.session.commit()
    flash(f"Deleted {name}. Reports you already made keep their device details.", "ok")
    return redirect(url_for("devices.list_devices"))
