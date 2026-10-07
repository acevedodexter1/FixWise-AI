"""Home page: device cards, quick problem chips and the device the user chose."""
import re

import pytest

from conftest import page, start
from services import symptom_service


def _chips(html):
    return re.findall(r'<button type="button" data-text="([^"]+)"', html)


def test_home_has_laptop_and_desktop_cards(client):
    html = page(client, "/")
    assert 'name="device_kind" value="laptop"' in html
    assert 'name="device_kind" value="desktop"' in html


def test_devices_without_guided_steps_are_shown_as_coming_soon_and_cannot_be_chosen(client):
    html = page(client, "/")
    assert html.count("Coming soon") == 2
    assert 'value="mobile"' not in html and 'value="router"' not in html
    assert html.count('type="radio"') == 2


def test_the_page_has_no_mock_conversation_and_no_empty_learn_page(client):
    html = page(client, "/")
    assert "Example conversation" not in html
    assert "Learn the basics" not in html and "/learn" not in html


def test_the_page_is_set_up_for_small_screens(client):
    assert 'name="viewport" content="width=device-width, initial-scale=1' in page(client, "/")


@pytest.mark.parametrize("text", _chips(open("templates/home.html", encoding="utf-8").read()))
def test_every_quick_problem_reaches_a_real_category_without_the_ai(text):
    assert symptom_service.detect_category(text) != "unknown", text


def test_there_are_quick_problems_to_tap(client):
    assert len(_chips(page(client, "/"))) >= 8


def test_the_chosen_device_card_is_remembered(client):
    client.post("/troubleshoot", data={"problem": "my wifi has no internet", "device_kind": "desktop"})
    with client.session_transaction() as browser_session:
        analysis = browser_session["ts"]["analysis"]
    assert analysis["device_type"] == "computer" and analysis["device"] == "Desktop PC"


def test_an_unknown_device_card_value_is_ignored(client):
    client.post("/troubleshoot", data={"problem": "my wifi has no internet", "device_kind": "toaster"})
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["analysis"]["device"] in ("", None)


def test_the_words_about_a_phone_beat_the_laptop_card(client):
    client.post("/troubleshoot", data={"problem": "my phone has no internet", "device_kind": "laptop"})
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["analysis"]["device_type"] == "mobile"


def test_a_hazard_is_still_referred_whatever_card_was_chosen(client):
    html = start(client, "my laptop is smoking")  # no card
    assert "Professional assistance" in html
    client.post("/troubleshoot", data={"problem": "my laptop is smoking", "device_kind": "laptop"})
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["node"] == "x_hazard"
