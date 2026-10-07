from datetime import datetime, timedelta

import pytest

import make_admin
from conftest import page
from extensions import db
from models import AIAnalysis, Device, TroubleshootingSession, User
from services import admin_service
from services import decision_tree_service as tree

ADMIN_PAGES = ["/admin", "/admin/users", "/admin/sessions", "/admin/knowledge", "/admin/error-cases",
               "/admin/ai", "/admin/knowledge/network"]


def _user(client, email, role="USER", name="Test"):
    with client.application.app_context():
        user = User(name=name, email=email, role=role)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, email, role="USER", name="Test"):
    user_id = _user(client, email, role, name)
    client.post("/login", data={"email": email, "password": "password123"})
    return user_id


def _session(client, user_id, status, category="network", problem="wifi problem", created=None):
    with client.application.app_context():
        row = TroubleshootingSession(
            user_id=user_id, problem_description=problem, category=category,
            current_node=tree.START_NODES[category], status=status,
            created_at=created or datetime.now(),
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# ---------- who can get in ----------

@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_anonymous_visitors_are_sent_to_log_in(client, url):
    response = client.get(url)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_normal_users_see_nothing(client, url):
    _login(client, "user@example.com")
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("url", ADMIN_PAGES)
def test_admins_can_open_every_page(client, url):
    _login(client, "admin@example.com", role="ADMIN")
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"


def test_admin_link_only_shows_for_admins(client):
    _login(client, "user@example.com")
    assert 'href="/admin"' not in page(client, "/")
    client.get("/logout")
    _login(client, "admin@example.com", role="ADMIN")
    assert 'href="/admin"' in page(client, "/")


def test_admin_pages_are_read_only(client):
    _login(client, "admin@example.com", role="ADMIN")
    for url in ADMIN_PAGES:
        assert client.post(url).status_code == 405


# ---------- the numbers ----------

def test_overview_counts(client):
    admin_id = _login(client, "admin@example.com", role="ADMIN")
    for status in ("RESOLVED", "RESOLVED", "RESOLVED", "ESCALATED", "ACTIVE", "UNRESOLVED"):
        _session(client, admin_id, status)
    _session(client, admin_id, "RESOLVED", category="usb", created=datetime.now() - timedelta(days=30))
    with client.application.app_context():
        db.session.add(Device(user_id=admin_id, name="PC", device_type="Desktop"))
        db.session.add(AIAnalysis(session_id=1, category="network", source="ai"))
        db.session.add(AIAnalysis(session_id=2, category="network", source="keywords"))
        db.session.commit()
        stats = admin_service.overview()
    assert stats["users"] == 1 and stats["admins"] == 1 and stats["devices"] == 1
    assert stats["sessions"] == 7 and stats["recent_sessions"] == 6
    # 4 resolved and 1 escalated reached a result: unfinished sessions do not count against success
    assert stats["resolved_rate"] == 80
    assert stats["by_category"][0] == {"key": "network", "label": "Internet and network", "count": 6}
    assert (stats["ai_analyses"], stats["keyword_analyses"]) == (1, 1)


def test_overview_with_no_data_does_not_divide_by_zero(client):
    _login(client, "admin@example.com", role="ADMIN")
    html = page(client, "/admin")
    assert "n/a" in html and "No sessions saved yet" in html


# ---------- lists ----------

def test_users_page_lists_session_counts(client):
    _login(client, "admin@example.com", role="ADMIN")
    user_id = _user(client, "student@example.com", name="Student")
    _session(client, user_id, "RESOLVED")
    _session(client, user_id, "ESCALATED")
    html = page(client, "/admin/users")
    assert "student@example.com" in html and "Student" in html
    row = html.split("student@example.com")[1].split("</tr>")[0]
    assert ">2<" in row


def test_session_filters_and_unknown_filter_values(client):
    admin_id = _login(client, "admin@example.com", role="ADMIN")
    _session(client, admin_id, "RESOLVED", problem="the resolved one")
    _session(client, admin_id, "ESCALATED", category="usb", problem="the usb one")
    assert "the usb one" not in page(client, "/admin/sessions?status=RESOLVED")
    assert "the resolved one" not in page(client, "/admin/sessions?category=usb")
    both = page(client, "/admin/sessions?status=BOGUS&category=nonsense%27%20OR%201=1")
    assert "the resolved one" in both and "the usb one" in both  # ignored, not trusted, not an error


def test_sessions_are_paginated_and_keep_filters(client):
    admin_id = _login(client, "admin@example.com", role="ADMIN")
    for number in range(admin_service.PAGE_SIZE + 3):
        _session(client, admin_id, "RESOLVED", problem=f"problem number {number}")
    first = page(client, "/admin/sessions?status=RESOLVED")
    assert "Page 1 of 2" in first and "status=RESOLVED" in first and "page=2" in first
    second = page(client, "/admin/sessions?status=RESOLVED&page=2")
    assert "Page 2 of 2" in second
    assert client.get("/admin/sessions?page=999").status_code == 200  # past the end: empty, not a crash
    assert client.get("/admin/sessions?page=abc").status_code == 200


def test_user_supplied_text_is_escaped(client):
    admin_id = _login(client, "admin@example.com", role="ADMIN", name="<b>Boss</b>")
    _session(client, admin_id, "RESOLVED", problem="<script>alert(1)</script>")
    for url in ("/admin/sessions", "/admin/users"):
        html = page(client, url)
        assert "<script>alert(1)</script>" not in html and "<b>Boss</b>" not in html


# ---------- knowledge base ----------

def test_knowledge_summary_covers_every_category():
    rows = admin_service.knowledge_summary()
    assert {r["key"] for r in rows} == set(tree.START_NODES) - {"unknown"}
    for row in rows:
        assert row["nodes"] == sum(row["counts"].values()) > 0


@pytest.mark.parametrize("category", sorted(set(tree.START_NODES) - {"unknown"}))
def test_outline_lists_every_node_once_starting_at_the_first_question(category):
    nodes = admin_service.outline(category)
    ids = [n["id"] for n in nodes]
    assert ids[0] == tree.START_NODES[category]
    assert len(ids) == len(set(ids))
    expected = [i for i in tree.TREE if tree.category_of(i) == category]
    assert sorted(ids) == sorted(expected)


@pytest.mark.parametrize("category", ["unknown", "nope", "x_hazard", "pick"])
def test_unknown_trees_are_404(client, category):
    _login(client, "admin@example.com", role="ADMIN")
    assert client.get(f"/admin/knowledge/{category}").status_code == 404


# ---------- AI settings ----------

def test_ai_page_never_shows_the_key_or_url_secrets(client):
    _login(client, "admin@example.com", role="ADMIN")
    client.application.config.update(
        AI_API_KEY="sk-super-secret-123", AI_BASE_URL="https://user:pw@api.example.com/v1?key=abc",
        AI_MODEL="some-model", AI_VISION_MODEL="",
    )
    try:
        html = page(client, "/admin/ai")
    finally:
        client.application.config.update(AI_API_KEY="", AI_BASE_URL="", AI_MODEL="")
    assert "sk-super-secret-123" not in html and "user:pw" not in html and "key=abc" not in html
    assert "api.example.com" in html and "some-model" in html


def test_ai_page_when_off(client):
    _login(client, "admin@example.com", role="ADMIN")
    assert "keyword matching only" in page(client, "/admin/ai")


# ---------- make_admin.py ----------

def test_make_admin_promotes_and_demotes(client):
    _user(client, "someone@example.com")
    assert make_admin.main(["make_admin.py", "Someone@Example.com"]) == 0
    with client.application.app_context():
        assert User.query.filter_by(email="someone@example.com").one().role == "ADMIN"
    assert make_admin.main(["make_admin.py", "someone@example.com", "--remove"]) == 0
    with client.application.app_context():
        assert User.query.filter_by(email="someone@example.com").one().role == "USER"


def test_make_admin_refuses_unknown_accounts_and_bad_usage(client, capsys):
    assert make_admin.main(["make_admin.py", "ghost@example.com"]) == 1
    assert "Register it on the website first" in capsys.readouterr().out
    assert make_admin.main(["make_admin.py"]) == 1
