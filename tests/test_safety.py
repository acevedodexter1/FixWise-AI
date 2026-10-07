import pytest

from conftest import page, start
from extensions import db
from models import TroubleshootingSession, User
from services import ai_service, safety_service


@pytest.mark.parametrize("text, expected", [
    ("my laptop smells like burning", "x_hazard"),
    ("there is smoke coming from the charger", "x_hazard"),
    ("the battery looks swollen", "x_hazard"),
    ("I spilled coffee on my keyboard", "x_hazard"),
    ("how do I solder a new chip onto my motherboard", "x_scope"),
    ("I want to repair the power supply myself", "x_scope"),
    ("my pc has no display, could it be the motherboard?", None),  # normal troubleshooting first
    ("my wifi is slow", None),
])
def test_check_request(text, expected):
    assert safety_service.check_request(text) == expected


def test_hazard_skips_the_ai_and_shows_referral(client, monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("the AI must not be called for a hazard")
    monkeypatch.setattr(ai_service, "analyze_problem", must_not_run)
    html = start(client, "my laptop smells like burning")
    assert "Professional assistance recommended" in html
    assert "unplug it" in html


def test_out_of_scope_repair_shows_the_safety_note(client):
    html = start(client, "how do I solder a new chip onto my motherboard")
    assert "Professional assistance recommended" in html
    assert "does not provide motherboard-level or electrical repair instructions" in html


def test_saved_session_is_marked_escalated(client):
    with client.application.app_context():
        user = User(name="Test", email="t@example.com")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
    client.post("/login", data={"email": "t@example.com", "password": "password123"})
    start(client, "there is smoke coming from my laptop")
    with client.application.app_context():
        row = TroubleshootingSession.query.one()
        assert row.status == "ESCALATED" and row.completed_at is not None
        assert "safety hazard" in row.final_result


CATEGORIES = {"network": "Internet", "unknown": "Not sure"}


def test_ai_overclaims_are_dropped():
    clean = safety_service.validate_analysis({
        "category": "network", "problem_summary": "No internet",
        "possible_causes": ["The Wi-Fi card is broken", "DNS problem", "Definitely the router"],
    }, CATEGORIES)
    assert clean["possible_causes"] == ["DNS problem"]
    assert "cannot inspect" in clean["warning"]


def test_ai_unknown_category_and_bad_shape():
    assert safety_service.validate_analysis({"category": "toaster"}, CATEGORIES)["category"] == "unknown"
    with pytest.raises(ValueError):
        safety_service.validate_analysis("not an object", CATEGORIES)


# --- Filipino / Taglish / Bisaya -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "may usok na lumalabas sa laptop ko",
    "amoy sunog yung charger",
    "nasunog ang charger ko",
    "namamaga na yung battery ng laptop",
    "ang baterya ng cp ko ay namamaga",
    "mihubag ang battery sa akong cp",
    "natapunan ng kape ang keyboard",
    "nalubog sa tubig ang cp ko",
    "nahulog sa tubig ang phone ko",
    "nabasa ang laptop ko ng ulan",
    "ang cp ko nabasa",
    "nabasa akong cp",
    "nagspark yung charger",
    "nakuryente ako sa charger",
    "naay aso gikan sa laptop",
    "naa'y baho nga sunog sa laptop",
])
def test_local_language_hazards_are_caught(text):
    assert safety_service.check_request(text) == "x_hazard"


@pytest.mark.parametrize("text", [
    "umiinit at namamatay phone ko kahit 60% battery",
    "mabagal ang wifi ko",
    "di mo connect akong wifi sa cp",
    "dili mo-charge akong cp",
    "nabasa ko yung error message sa laptop",  # "nabasa ko" means "I read", not "got wet"
    "nabasa ko sa phone na may update",
    "nag-hang ang computer",
    "walang tunog ang laptop ko",
    "namamaga ang daliri ko sa kaka-type",  # swollen, but not a battery
    "mabilis maubos ang baterya ko",
    "ayusin ko ba ang wifi settings",
])
def test_ordinary_local_language_problems_are_not_flagged(text):
    assert safety_service.check_request(text) is None


@pytest.mark.parametrize("text", [
    "gusto kong ayusin ang motherboard",
    "pwede ko bang buksan ang power supply",
    "palitan ko ang capacitor",
    "magsolder ako ng chip",
    "ayuhon nako ang motherboard",
])
def test_local_language_repairs_are_out_of_scope(text):
    assert safety_service.check_request(text) == "x_scope"


def test_local_hazard_skips_the_ai_and_never_starts_steps(client, monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("the AI must not be called for a hazard")
    monkeypatch.setattr(ai_service, "analyze_problem", must_not_run)
    html = start(client, "amoy sunog yung charger ng laptop ko")
    assert "unplug it" in html
