from datetime import datetime
from io import BytesIO

import pytest

from conftest import start
from extensions import db
from models import TroubleshootingSession, User
from services import decision_tree_service as tree
from services import report_service


def _make_user(client, email):
    with client.application.app_context():
        user = User(name="Test", email=email)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()


def _login(client, email="t@example.com"):
    _make_user(client, email)
    client.post("/login", data={"email": email, "password": "password123"})


def _walk_to_end(client, step_choice):
    """Answer the first option on questions and `step_choice` on steps until a result is reached."""
    for _ in range(40):
        with client.session_transaction() as s:
            node = tree.TREE[s["ts"]["node"]]
        if node["type"] not in ("question", "step"):
            return node
        choice = "0" if node["type"] == "question" else step_choice
        client.post("/troubleshoot/answer", data={"choice": choice})
    raise AssertionError("the interview never ended")


def _pdf_text(data):
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() for page in reader.pages)


# ---------- the report data ----------

def test_resolved_report():
    node = tree.TREE[tree.START_NODES["network"]]
    while node["type"] != "resolved":
        node = tree.TREE[node["options"][0]["next"] if node["type"] == "question" else node["fixed"]]
    report = report_service.build_report(
        "wifi connected but no websites", "network", node,
        [{"text": "A step", "answer": "It worked"}], now=datetime(2026, 10, 5, 9, 30),
    )
    assert report["status"] == "RESOLVED" and report["outcome"]["kind"] == "resolved"
    assert report["category"] == tree.CATEGORY_LABELS["network"]
    assert report["reference"] == report_service.GUEST_REFERENCE
    assert report["filename"] == "fixwise-report-guest.pdf"
    assert report["generated"] == "Oct 05, 2026, 09:30 AM"
    assert "not a confirmed finding" in report["outcome"]["text"]


def test_hazard_report_has_no_steps_and_says_so():
    report = report_service.build_report("it smells like burning", "unknown", tree.TREE["x_hazard"], [])
    assert report["status"] == "ESCALATED" and report["steps"] == []
    text = report_service.as_text(report)
    assert "referred before any step was tried" in text
    assert "Possible causes (not confirmed)" in text


def test_unfinished_and_abandoned_sessions_are_labelled():
    node = tree.TREE[tree.START_NODES["usb"]]
    active = report_service.build_report("usb problem", "usb", node, [])
    assert active["status"] == "ACTIVE" and active["outcome"]["kind"] == "open"
    abandoned = report_service.build_report("usb problem", "usb", node, [], status="UNRESOLVED")
    assert abandoned["status_label"] == "Not finished"
    assert "started over" in abandoned["outcome"]["text"]


def test_ai_analysis_is_labelled_and_empty_analysis_is_hidden():
    node = tree.TREE["x_scope"]
    ai = {"summary": "No sound", "symptoms": ["silent"], "possible_causes": ["driver"], "source": "ai"}
    report = report_service.build_report("p", "unknown", node, [], analysis=ai)
    assert report["analysis"]["ai"] is True
    assert "(AI-generated, not verified)" in report_service.as_text(report)
    empty = {"summary": "", "symptoms": [], "possible_causes": [], "source": "keywords"}
    assert report_service.build_report("p", "unknown", node, [], analysis=empty)["analysis"] is None


def test_every_category_produces_a_valid_pdf():
    for category, start_node in tree.START_NODES.items():
        for choice in ("fixed", "not_fixed"):
            node_id = start_node
            while tree.TREE[node_id]["type"] in ("question", "step"):
                node = tree.TREE[node_id]
                node_id = node["options"][0]["next"] if node["type"] == "question" else node[choice]
            report = report_service.build_report("problem", category, tree.TREE[node_id], [])
            data = report_service.build_pdf(report)
            assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")


# ---------- the PDF itself ----------

def test_pdf_survives_markup_emoji_and_very_long_text():
    nasty = "<b>bold</b> & <para> ñ é “quotes” 😀 日本語 \x00\x07 " + "word " * 600
    steps = [{"text": f"Step {i} <i>x</i>", "answer": "Still not working & tried"} for i in range(60)]
    report = report_service.build_report(nasty, "usb", tree.TREE["x_scope"], steps)
    data = report_service.build_pdf(report)
    assert data.startswith(b"%PDF")


def test_pdf_contains_the_report_content():
    steps = [{"text": "Check power, paper and cables", "answer": "Still not working"}]
    report = report_service.build_report(
        "my printer will not print", "printer", tree.TREE["x_scope"], steps,
        reference="FW-000007", started=datetime(2026, 10, 5, 8, 0),
    )
    text = _pdf_text(report_service.build_pdf(report))
    assert "Troubleshooting Report" in text
    assert "FW-000007" in text
    assert "my printer will not print" in text
    assert "Check power, paper and cables" in text
    assert "Professional assistance recommended" in text
    assert "cannot inspect your device" in text


def test_pdf_keeps_typed_markup_as_plain_text():
    report = report_service.build_report("<b>not bold</b> & more", "usb", tree.TREE["x_scope"], [])
    assert "<b>not bold</b> & more" in _pdf_text(report_service.build_pdf(report))


# ---------- guest routes ----------

def test_guest_report_page_and_pdf(client):
    start(client, "there is smoke coming from my laptop")
    page = client.get("/troubleshoot/report")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Troubleshooting Report" in html and "Guest session (not saved)" in html
    assert "smoke coming from my laptop" in html
    assert "Download PDF" in html
    assert page.headers["Cache-Control"] == "no-store"

    pdf = client.get("/troubleshoot/report.pdf")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF")
    assert "attachment" in pdf.headers["Content-Disposition"]
    assert "fixwise-report-guest.pdf" in pdf.headers["Content-Disposition"]
    assert pdf.headers["Cache-Control"] == "no-store"


def test_report_is_escaped_on_the_page(client):
    start(client, "my usb drive says <script>alert(1)</script> & is not detected")
    html = client.get("/troubleshoot/report").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_report_without_an_interview_goes_home(client):
    for url in ("/troubleshoot/report", "/troubleshoot/report.pdf"):
        response = client.get(url)
        assert response.status_code == 302 and response.headers["Location"] == "/"


def test_finished_interview_links_to_the_report(client):
    start(client, "my usb flash drive is not detected")
    _walk_to_end(client, "not_fixed")
    html = client.get("/troubleshoot/interview").get_data(as_text=True)
    assert "/troubleshoot/report" in html and "/troubleshoot/report.pdf" in html


def test_guest_report_lists_what_was_tried(client):
    start(client, "my usb flash drive is not detected")
    end = _walk_to_end(client, "not_fixed")
    html = client.get("/troubleshoot/report").get_data(as_text=True)
    assert "Professional assistance recommended" in html
    assert "Still not working" in html
    assert end["causes"][0] in html


# ---------- saved sessions ----------

def test_saved_session_report_and_pdf(client):
    _login(client)
    start(client, "my usb flash drive is not detected")
    _walk_to_end(client, "not_fixed")
    with client.application.app_context():
        session_id = TroubleshootingSession.query.one().id

    page = client.get(f"/dashboard/session/{session_id}/report")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert f"FW-{session_id:06d}" in html and "Session started" in html
    assert "Professional assistance recommended" in html

    pdf = client.get(f"/dashboard/session/{session_id}/report.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert f"fixwise-report-FW-{session_id:06d}.pdf" in pdf.headers["Content-Disposition"]


def test_history_page_links_to_the_report(client):
    _login(client)
    start(client, "my usb flash drive is not detected")
    _walk_to_end(client, "not_fixed")
    with client.application.app_context():
        session_id = TroubleshootingSession.query.one().id
    html = client.get(f"/dashboard/session/{session_id}").get_data(as_text=True)
    assert f"/dashboard/session/{session_id}/report.pdf" in html


def test_someone_elses_report_is_not_found(client):
    _login(client, "owner@example.com")
    start(client, "there is smoke coming from my laptop")
    with client.application.app_context():
        session_id = TroubleshootingSession.query.one().id
    client.get("/logout")
    _login(client, "other@example.com")
    assert client.get(f"/dashboard/session/{session_id}/report").status_code == 404
    assert client.get(f"/dashboard/session/{session_id}/report.pdf").status_code == 404


def test_saved_report_needs_a_login(client):
    for url in ("/dashboard/session/1/report", "/dashboard/session/1/report.pdf"):
        response = client.get(url)
        assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_resumed_session_keeps_its_analysis(client, monkeypatch):
    from services import ai_service

    def fake(problem, categories, fallback):
        return {"category": "usb", "summary": "A USB drive is not detected", "symptoms": ["no drive letter"],
                "possible_causes": ["Loose connection"], "priority": "Medium", "warning": "w",
                "source": "ai", "raw": "{}"}

    monkeypatch.setattr(ai_service, "analyze_problem", fake)
    _login(client)
    start(client, "my usb flash drive is not detected")
    with client.application.app_context():
        session_id = TroubleshootingSession.query.one().id
    client.get(f"/dashboard/session/{session_id}/resume")
    with client.session_transaction() as s:
        assert s["ts"]["analysis"]["summary"] == "A USB drive is not detected"
    html = client.get(f"/dashboard/session/{session_id}/report").get_data(as_text=True)
    assert "A USB drive is not detected" in html and "AI-generated, not verified" in html
