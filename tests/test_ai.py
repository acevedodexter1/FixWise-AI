"""Understanding the problem: device normalization, confidence, and the AI-off fallback."""
import json

import pytest

from conftest import start
from services import ai_service, safety_service, symptom_service

CATEGORIES = {"battery": "Battery and charging", "network": "Internet and network", "unknown": "Not sure yet"}


# --- normalization ----------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("di mo connect akong wifi sa cp", "mobile"),
    ("my android keeps restarting", "mobile"),
    ("dili mo-charge akong selpon", "mobile"),
    ("my iPad screen is black", "tablet"),
    ("laptop ko ay mabagal", "computer"),
    ("the pc is slow", "computer"),
    ("router won't connect my phone", "networking"),  # the first device named wins
    ("phone can't reach the router", "mobile"),
    ("Arduino sensor reading is wrong", "electronics"),
    ("my headphone is broken", "unknown"),  # "headphone" must not match "phone"
    ("something is wrong", "unknown"),
])
def test_detect_device(text, expected):
    assert symptom_service.detect_device(text) == expected


@pytest.mark.parametrize("value, expected", [
    ("Android phone", "mobile"),
    ("mobile_device", "mobile"),
    ("computer", "computer"),
    ("Windows PC", "computer"),
    ("toaster", "unknown"),
    (None, "unknown"),
    (42, "unknown"),
])
def test_normalize_device(value, expected):
    assert symptom_service.normalize_device(value) == expected


@pytest.mark.parametrize("value, expected", [
    (0.91, 0.91), ("0.91", 0.91), (91, 0.91), ("91%", 0.91), ("0.5", 0.5), (0, 0.0), (1, 1.0),
    ("high", None), (None, None), (True, None), (-1, None), (150, None),
])
def test_clean_confidence(value, expected):
    assert symptom_service.clean_confidence(value) == expected


@pytest.mark.parametrize("text, expected", [
    ("walang tunog ang laptop ko", "audio"),
    ("mabagal ang laptop ko", "performance"),
    ("lowbat agad ang baterya", "battery"),
    ("walay internet akong cp", "network"),
    ("kulang sa space ang computer", "storage"),
    ("hello po", "unknown"),
])
def test_local_words_work_without_the_ai(text, expected):
    assert symptom_service.detect_category(text) == expected


# --- validation and confidence ----------------------------------------------------------------

def test_validate_analysis_adds_standard_device_and_confidence():
    clean = safety_service.validate_analysis({
        "category": "battery", "problem_summary": "Phone will not charge",
        "device": "Android Phone", "device_type": "Android phone",
        "device_confidence": "94%", "category_confidence": 0.89,
    }, CATEGORIES)
    assert clean["device_type"] == "mobile"
    assert clean["device_confidence"] == 0.94 and clean["category_confidence"] == 0.89
    assert clean["low_confidence"] is False


def test_validate_analysis_without_the_new_fields_still_works():
    clean = safety_service.validate_analysis({"category": "network"}, CATEGORIES)
    assert clean["device_type"] == "unknown"
    assert clean["device_confidence"] is None and clean["category_confidence"] is None


def test_low_confidence_asks_instead_of_guessing():
    analysis = safety_service.validate_analysis({"category": "battery", "category_confidence": 0.41}, CATEGORIES)
    analysis = safety_service.apply_confidence(analysis)
    assert analysis["category"] == "unknown" and analysis["low_confidence"] is True


def test_missing_or_high_confidence_keeps_the_category():
    for confidence in (None, 0.5, 0.9):
        analysis = safety_service.validate_analysis(
            {"category": "battery", "category_confidence": confidence}, CATEGORIES)
        assert safety_service.apply_confidence(analysis)["category"] == "battery"


# --- analyze_problem with the AI switched on --------------------------------------------------

@pytest.fixture
def ai_on(client, monkeypatch):
    monkeypatch.setitem(client.application.config, "AI_API_KEY", "test-key")
    return client.application


def _fake_reply(monkeypatch, payload):
    monkeypatch.setattr(ai_service, "_call_model", lambda *a, **k: json.dumps(payload))


def test_analyze_problem_returns_device_and_confidence(ai_on, monkeypatch):
    _fake_reply(monkeypatch, {
        "device": "Android phone", "device_type": "mobile", "device_confidence": 0.94,
        "category": "battery", "category_confidence": 0.89, "problem_summary": "Phone is not charging",
        "symptoms": ["charging stops"], "possible_causes": ["cable"], "priority": "Low",
    })
    with ai_on.app_context():
        result = ai_service.analyze_problem("dili mo-charge akong cp", CATEGORIES, fallback=lambda p: "unknown")
    assert result["source"] == "ai" and result["category"] == "battery"
    assert result["device_type"] == "mobile" and result["device_confidence"] == 0.94


def test_analyze_problem_low_confidence_becomes_unknown(ai_on, monkeypatch):
    _fake_reply(monkeypatch, {"category": "network", "category_confidence": 0.3, "problem_summary": "Unclear"})
    with ai_on.app_context():
        result = ai_service.analyze_problem("hindi gumagana", CATEGORIES, fallback=lambda p: "unknown")
    assert result["category"] == "unknown" and result["low_confidence"] is True


def test_analyze_problem_fills_in_the_device_from_the_words(ai_on, monkeypatch):
    _fake_reply(monkeypatch, {"category": "battery", "category_confidence": 0.9, "device_type": "unknown"})
    with ai_on.app_context():
        result = ai_service.analyze_problem("mabilis maubos ang baterya ng cp ko", CATEGORIES,
                                            fallback=lambda p: "unknown")
    assert result["device_type"] == "mobile"


def test_analyze_problem_falls_back_to_keywords_when_the_ai_fails(ai_on, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(ai_service, "_call_model", boom)
    with ai_on.app_context():
        result = ai_service.analyze_problem("walay internet akong cp", CATEGORIES,
                                            fallback=symptom_service.detect_category)
    assert result["source"] == "keywords" and result["category"] == "network"
    assert result["device_type"] == "mobile"


def test_the_prompt_lists_the_device_types_and_asks_for_confidence():
    prompt = ai_service._build_prompt(CATEGORIES)
    assert '"mobile"' in prompt and "category_confidence" in prompt and "device_confidence" in prompt


# --- end to end, AI off -----------------------------------------------------------------------

def test_taglish_problem_without_ai_reaches_the_right_area(client):
    html = start(client, "walang tunog ang laptop ko")
    assert "<h1>Audio</h1>" in html
    with client.session_transaction() as browser_session:
        analysis = browser_session["ts"]["analysis"]
    assert analysis["device_type"] == "computer" and analysis["source"] == "keywords"


def test_phone_problem_is_recognised_as_a_phone_without_ai(client):
    start(client, "dili mo-charge akong selpon")
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["analysis"]["device_type"] == "mobile"
        assert browser_session["ts"]["category"] == "battery"


def test_device_and_confidence_are_shown_when_the_ai_understood(client, monkeypatch):
    monkeypatch.setitem(client.application.config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "_call_model", lambda *a, **k: json.dumps({
        "device": "Android phone", "device_type": "mobile", "device_confidence": 0.94,
        "category": "battery", "category_confidence": 0.89, "problem_summary": "The phone is not charging",
    }))
    html = start(client, "dili mo-charge akong cp")
    assert "Device:" in html and "Android phone" in html and "94% sure" in html


def test_low_confidence_shows_the_note_and_the_pick_question(client, monkeypatch):
    monkeypatch.setitem(client.application.config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "_call_model", lambda *a, **k: json.dumps({
        "category": "network", "category_confidence": 0.3, "problem_summary": "The problem is unclear",
    }))
    html = start(client, "hindi gumagana")
    assert "ask instead of guessing" in html and "Which sounds closest" in html


def test_unknown_problem_still_asks_which_area(client):
    html = start(client, "hello po")
    assert "which sounds closest" in html.lower() or "not sure yet" in html.lower()


# --- the user's own words beat the AI about the device ----------------------------------------

def test_detect_devices_lists_every_device_in_order():
    assert symptom_service.detect_devices("my phone cannot reach the router") == ["mobile", "networking"]
    assert symptom_service.detect_devices("hello") == []


def test_device_hint_only_when_exactly_one_kind_is_named():
    assert symptom_service.device_hint("yung cp ko ay mainit") == "mobile"
    assert symptom_service.device_hint("my phone cannot reach the router") is None
    assert symptom_service.device_hint("hindi gumagana") is None


@pytest.mark.parametrize("ai_type, text, expected", [
    ("computer", "yung cp ko 5 mins lang gagamitin sobrang init", ("mobile", True)),
    ("mobile", "yung cp ko ay mainit", ("mobile", False)),
    ("computer", "my phone cannot reach the router", ("computer", False)),  # two devices: trust the AI
    ("unknown", "my phone cannot reach the router", ("mobile", False)),  # AI had no idea: first named
    ("computer", "hindi gumagana", ("computer", False)),  # no device words: trust the AI
    ("unknown", "hindi gumagana", ("unknown", False)),
])
def test_reconcile_device(ai_type, text, expected):
    assert symptom_service.reconcile_device(ai_type, text) == expected


def test_cp_is_a_phone_even_when_the_ai_says_computer(ai_on, monkeypatch):
    _fake_reply(monkeypatch, {
        "device": "computer", "device_type": "computer", "device_confidence": 0.8,
        "category": "performance", "category_confidence": 0.8, "problem_summary": "The computer gets very hot",
    })
    with ai_on.app_context():
        result = ai_service.analyze_problem("yung cp ko 5 mins lang gagamitin sobrang initna", CATEGORIES,
                                            fallback=lambda p: "unknown")
    assert result["device_type"] == "mobile"
    assert result["device"] == "Mobile phone" and result["device_confidence"] is None


def test_the_ai_is_told_which_device_the_words_point_to(ai_on, monkeypatch):
    seen = []

    def capture(system_prompt, user_text, **kwargs):
        seen.append(system_prompt)
        return json.dumps({"category": "battery", "category_confidence": 0.9})
    monkeypatch.setattr(ai_service, "_call_model", capture)
    with ai_on.app_context():
        ai_service.analyze_problem("yung cp ko ay mainit", CATEGORIES, fallback=lambda p: "unknown")
        ai_service.analyze_problem("hindi gumagana", CATEGORIES, fallback=lambda p: "unknown")
    assert 'point to the device type "mobile"' in seen[0]
    assert "Keyword check" not in seen[1]

