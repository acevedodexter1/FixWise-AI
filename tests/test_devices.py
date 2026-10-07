import json

import pytest

from conftest import page, start
from extensions import db
from models import Device, SessionDevice, TroubleshootingSession, User
from services import device_service, report_service
from services import decision_tree_service as tree


def _make_user(client, email="t@example.com"):
    with client.application.app_context():
        user = User(name="Test", email=email)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, email="t@example.com"):
    user_id = _make_user(client, email)
    client.post("/login", data={"email": email, "password": "password123"})
    return user_id


def _device_form(**overrides):
    data = {"name": "School laptop", "device_type": "Laptop", "brand": "Acer", "model": "Aspire 5",
            "os": "Windows 11", "notes": "Battery replaced in 2024."}
    data.update(overrides)
    return data


def _add(client, **overrides):
    return client.post("/dashboard/devices/add", data=_device_form(**overrides), follow_redirects=True)


def _device_id(client, name="School laptop"):
    with client.application.app_context():
        return Device.query.filter_by(name=name).first().id


# ---------- the device pages ----------

def test_devices_need_a_login(client):
    for url in ("/dashboard/devices", "/dashboard/devices/add"):
        response = client.get(url)
        assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_add_list_edit_and_delete(client):
    _login(client)
    assert "not saved a device yet" in page(client, "/dashboard/devices")

    html = _add(client).get_data(as_text=True)
    assert "School laptop" in html and "Acer Aspire 5" in html and "Windows 11" in html

    device_id = _device_id(client)
    client.post(f"/dashboard/devices/{device_id}/edit", data=_device_form(name="Home PC", device_type="Desktop"))
    assert "Home PC" in page(client, "/dashboard/devices")

    client.post(f"/dashboard/devices/{device_id}/delete")
    assert "not saved a device yet" in page(client, "/dashboard/devices")


def test_name_is_required_and_bad_choices_are_rejected(client):
    _login(client)
    assert "This field is required" in _add(client, name="").get_data(as_text=True)
    assert "Not a valid choice" in _add(client, device_type="Toaster").get_data(as_text=True)
    assert "Not a valid choice" in _add(client, os="TempleOS").get_data(as_text=True)
    with client.application.app_context():
        assert Device.query.count() == 0


def test_notes_are_capped(client):
    _login(client)
    assert "Field cannot be longer than 300" in _add(client, notes="x" * 301).get_data(as_text=True)


def test_other_peoples_devices_are_not_reachable(client):
    _login(client, "owner@example.com")
    _add(client)
    device_id = _device_id(client)
    client.get("/logout")
    _login(client, "other@example.com")
    assert client.get(f"/dashboard/devices/{device_id}/edit").status_code == 404
    assert client.post(f"/dashboard/devices/{device_id}/edit", data=_device_form(name="Hacked")).status_code == 404
    assert client.post(f"/dashboard/devices/{device_id}/delete").status_code == 404
    with client.application.app_context():
        assert db.session.get(Device, device_id).name == "School laptop"


def test_delete_requires_post(client):
    _login(client)
    _add(client)
    assert client.get(f"/dashboard/devices/{_device_id(client)}/delete").status_code == 405


def test_device_limit(client):
    _login(client)
    for number in range(10):
        _add(client, name=f"PC {number}")
    html = _add(client, name="One too many").get_data(as_text=True)
    assert "up to 10 devices" in html
    with client.application.app_context():
        assert Device.query.count() == 10


def test_device_name_cannot_break_out_of_the_delete_prompt(client):
    import re
    _login(client)
    _add(client, name="O'Brien'); alert(1); ('")
    html = page(client, "/dashboard/devices")
    handler = re.search(r'onsubmit="([^"]*)"', html).group(1)
    assert "alert" not in handler and "Brien" not in handler  # the name is never inside the script
    assert 'data-name="O&#39;Brien&#39;); alert(1); (&#39;"' in html  # it travels as escaped data


# ---------- choosing a device for a troubleshooting session ----------

def test_home_offers_the_picker_only_to_signed_in_users_with_devices(client):
    assert "Which device is this about" not in page(client, "/")
    _login(client)
    assert "Add a device" in page(client, "/")
    _add(client)
    assert "Which device is this about" in page(client, "/")


def test_session_remembers_the_chosen_device(client):
    _login(client)
    _add(client)
    device_id = _device_id(client)
    client.post("/troubleshoot", data={"problem": "my wifi has no internet", "device_id": str(device_id)})
    with client.application.app_context():
        row = SessionDevice.query.one()
        assert row.device_id == device_id
        assert json.loads(row.snapshot)["model"] == "Aspire 5"


def test_someone_elses_device_id_is_ignored(client):
    _login(client, "owner@example.com")
    _add(client)
    device_id = _device_id(client)
    client.get("/logout")
    _login(client, "other@example.com")
    client.post("/troubleshoot", data={"problem": "my wifi has no internet", "device_id": str(device_id)})
    with client.application.app_context():
        assert SessionDevice.query.count() == 0


def test_guests_cannot_attach_a_device(client):
    start(client, "my wifi has no internet")
    client.post("/troubleshoot", data={"problem": "my wifi has no internet", "device_id": "1"})
    with client.application.app_context():
        assert SessionDevice.query.count() == 0


@pytest.mark.parametrize("bad", ["abc", "-1", "1; DROP TABLE devices", "", "99999"])
def test_bad_device_ids_are_harmless(client, bad):
    _login(client)
    response = client.post("/troubleshoot", data={"problem": "my wifi has no internet", "device_id": bad})
    assert response.status_code == 302
    with client.application.app_context():
        assert SessionDevice.query.count() == 0


def test_no_device_chosen_works_as_before(client):
    _login(client)
    _add(client)
    start(client, "my wifi has no internet")
    with client.application.app_context():
        assert TroubleshootingSession.query.count() == 1 and SessionDevice.query.count() == 0


# ---------- the device in reports ----------

def _escalated_session_with_device(client, **device_overrides):
    _login(client)
    _add(client, **device_overrides)
    device_id = _device_id(client, device_overrides.get("name", "School laptop"))
    client.post("/troubleshoot", data={"problem": "my wifi has no internet", "device_id": str(device_id)})
    for _ in range(40):
        with client.session_transaction() as s:
            node = tree.TREE[s["ts"]["node"]]
        if node["type"] not in ("question", "step"):
            break
        client.post("/troubleshoot/answer", data={"choice": "0" if node["type"] == "question" else "not_fixed"})
    with client.application.app_context():
        return TroubleshootingSession.query.one().id, device_id


def test_report_page_and_text_include_the_device(client):
    session_id, _ = _escalated_session_with_device(client)
    html = page(client, f"/dashboard/session/{session_id}/report")
    assert "School laptop: Laptop, Acer Aspire 5, Windows 11" in html
    assert "Device notes" in html and "Battery replaced in 2024." in html
    assert "Device: School laptop: Laptop, Acer Aspire 5, Windows 11" in html  # the plain-text version


def test_current_report_of_a_signed_in_user_includes_the_device(client):
    _escalated_session_with_device(client)
    assert "Acer Aspire 5" in page(client, "/troubleshoot/report")


def test_pdf_includes_the_device(client):
    session_id, _ = _escalated_session_with_device(client)
    response = client.get(f"/dashboard/session/{session_id}/report.pdf")
    assert response.status_code == 200 and response.data.startswith(b"%PDF")
    pypdf = pytest.importorskip("pypdf")
    from io import BytesIO
    text = "\n".join(p.extract_text() for p in pypdf.PdfReader(BytesIO(response.data)).pages)
    assert "Acer Aspire 5" in text


def test_report_without_a_device_has_no_device_rows(client):
    _login(client)
    start(client, "my wifi has no internet")
    with client.application.app_context():
        session_id = TroubleshootingSession.query.one().id
    html = page(client, f"/dashboard/session/{session_id}/report")
    assert "<dt>Device</dt>" not in html


def test_old_reports_keep_their_device_after_edit_and_delete(client):
    session_id, device_id = _escalated_session_with_device(client)
    client.post(f"/dashboard/devices/{device_id}/edit", data=_device_form(name="Renamed", model="Changed"))
    assert "Aspire 5" in page(client, f"/dashboard/session/{session_id}/report")
    client.post(f"/dashboard/devices/{device_id}/delete")
    assert "Aspire 5" in page(client, f"/dashboard/session/{session_id}/report")
    with client.application.app_context():
        assert SessionDevice.query.one().device_id is None


def test_session_detail_shows_the_device(client):
    session_id, _ = _escalated_session_with_device(client)
    assert "Device: School laptop" in page(client, f"/dashboard/session/{session_id}")


def test_hostile_text_in_device_fields_is_escaped_in_the_report(client):
    session_id, _ = _escalated_session_with_device(client, notes="<script>alert(1)</script>")
    html = page(client, f"/dashboard/session/{session_id}/report")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_summary_handles_partial_details():
    assert device_service.summary(None) == ""
    assert device_service.summary({"name": "PC"}) == "PC"
    assert device_service.summary({"name": "PC", "type": "Desktop", "os": "Linux"}) == "PC: Desktop, Linux"
    assert report_service._device_info({"name": "PC", "notes": "  "})["notes"] == ""
