"""Startup and blue screen category: the tree, the stop-code error cases and how they are reached."""
import json

import pytest

from conftest import page, start
from services import ai_service, decision_tree_service as tree, knowledge_service, symptom_service

STOP_CODES = [
    "HAL_INITIALIZATION_FAILED", "INACCESSIBLE_BOOT_DEVICE", "UNMOUNTABLE_BOOT_VOLUME",
    "CRITICAL_PROCESS_DIED", "SYSTEM_SERVICE_EXCEPTION", "SYSTEM_THREAD_EXCEPTION_NOT_HANDLED",
    "IRQL_NOT_LESS_OR_EQUAL", "PAGE_FAULT_IN_NONPAGED_AREA", "MEMORY_MANAGEMENT",
    "KERNEL_SECURITY_CHECK_FAILURE", "WHEA_UNCORRECTABLE_ERROR", "DPC_WATCHDOG_VIOLATION",
    "CLOCK_WATCHDOG_TIMEOUT",
]


def _boot_nodes():
    return {k: v for k, v in tree.TREE.items() if k.startswith("w_")}


def _answer(client, choice):
    return client.post("/troubleshoot/answer", data={"choice": choice}, follow_redirects=True).get_data(as_text=True)


def _fake_ai(monkeypatch, client, payload):
    monkeypatch.setitem(client.application.config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(ai_service, "_call_model", lambda *a, **k: json.dumps(payload))


# --- the tree -----------------------------------------------------------------------------------

def test_the_category_exists_and_starts_with_a_question():
    assert tree.CATEGORY_LABELS["boot"] == "Startup and blue screen"
    assert tree.TREE[tree.START_NODES["boot"]]["type"] == "question"
    assert tree.category_of("w_unplug") == "boot"


def test_no_boot_step_is_high_risk_and_every_medium_step_has_a_caution():
    steps = [n for n in _boot_nodes().values() if n["type"] == "step"]
    assert steps
    for node in steps:
        assert node.get("risk", "low") in ("low", "medium")
        assert not node.get("requires_professional")
        if node.get("risk") == "medium":
            assert node["caution"].strip()


def test_the_forced_shutdown_step_warns_about_updates_and_the_charger():
    node = tree.TREE["w_recovery"]
    assert node["risk"] == "medium"
    assert "Working on updates" in node["caution"] and "charger" in node["caution"]


def test_nothing_in_the_boot_steps_edits_the_bios_or_opens_the_hardware():
    text = " ".join(
        " ".join(str(node.get(f, "")) for f in ("do", "text", "title"))
        for node in _boot_nodes().values()
        if node["type"] in ("step", "question")
    ).lower()
    for forbidden in ("bios", "uefi", "screwdriver", "open the case", "bootrec", "fixmbr", "diskpart",
                      "reset this pc", "format"):
        assert forbidden not in text, forbidden


def test_the_memory_test_question_tells_the_user_to_save_work_first():
    assert "save your work" in tree.TREE["w_mem"]["text"].lower()


def test_dead_end_cases_lead_to_a_technician():
    for node_id in ("w_pro_nostart", "w_pro_startup", "w_pro_random", "w_pro_memory"):
        assert tree.TREE[node_id]["type"] == "escalate"
    assert tree.TREE["w_pro_nostart"]["hardware"] and tree.TREE["w_pro_memory"]["hardware"]


def test_the_pick_question_offers_the_new_category():
    labels = [o["label"] for o in tree.TREE["pick"]["options"]]
    assert "Windows will not start, shows a blue screen, or keeps restarting" in labels


# --- stop-code error cases ----------------------------------------------------------------------

@pytest.mark.parametrize("code", STOP_CODES)
def test_every_stop_code_is_a_known_boot_error(code):
    case = knowledge_service.match_error(f"Your PC ran into a problem. Stop code: {code}")
    assert case is not None and case["category"] == "boot", code


def test_a_stop_code_written_with_spaces_also_matches():
    assert knowledge_service.match_error("stop code: critical process died")["id"] == "boot_critical_process"


def test_ordinary_words_about_memory_do_not_match_a_blue_screen_case():
    assert knowledge_service.match_error("how does memory management work in windows") is None


@pytest.mark.parametrize("text", [
    "No bootable device", "Operating system not found", "Preparing Automatic Repair",
    "Reboot and select proper boot device", "0xc000000f",
])
def test_startup_messages_are_boot_errors(text):
    assert knowledge_service.match_error(text)["category"] == "boot", text


def test_the_display_driver_error_stays_in_display():
    assert knowledge_service.match_error("VIDEO_TDR_FAILURE nvlddmkm")["category"] == "display"


def test_boot_cases_never_state_a_cause_as_certain():
    for case in knowledge_service.ERROR_CASES:
        if case["category"] == "boot":
            assert len(case["causes"]) >= 2  # several possibilities, never one certainty
            assert "definitely" not in case["meaning"].lower()


# --- keyword fallback (AI off) ------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("my laptop shows a blue screen", "boot"),
    ("blue-screen every morning", "boot"),
    ("windows won't start", "boot"),
    ("laptop keeps restarting", "boot"),
    ("asul na screen sa laptop", "boot"),
    ("ayaw mag-on ang laptop ko", "boot"),
    ("black screen", "display"),
    ("the screen is flickering", "display"),
    ("slow computer", "performance"),
])
def test_keyword_fallback_prefers_the_more_specific_phrase(text, expected):
    assert symptom_service.detect_category(text) == expected


# --- end to end ---------------------------------------------------------------------------------

def test_a_typed_stop_code_reaches_the_boot_tree_without_the_ai(client):
    html = start(client, "HAL_INITIALIZATION_FAILED")
    assert "<h1>Startup and blue screen</h1>" in html
    assert "What happens when you turn the computer on?" in html


def test_a_known_error_beats_the_ais_wrong_guess(client, monkeypatch):
    _fake_ai(monkeypatch, client, {"category": "display", "category_confidence": 0.9, "device_type": "computer",
                                   "problem_summary": "Blank screen"})
    html = start(client, "my laptop shows HAL_INITIALIZATION_FAILED and a blank screen")
    assert "<h1>Startup and blue screen</h1>" in html
    with client.session_transaction() as browser_session:
        ts = browser_session["ts"]
    assert ts["category"] == "boot" and ts["analysis"]["category_confidence"] is None


def test_a_vague_known_error_does_not_override_the_ai(client, monkeypatch):
    _fake_ai(monkeypatch, client, {"category": "network", "category_confidence": 0.9, "device_type": "computer"})
    start(client, "chrome says not responding when I open a website")
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["category"] == "network"


def test_a_vague_known_error_fills_a_gap_when_nothing_else_knows(client):
    start(client, "everything says not responding")
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["category"] == "performance"


def test_a_hazard_still_beats_a_blue_screen(client):
    html = start(client, "blue screen and my laptop is smoking")
    assert "Professional assistance" in html
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["node"] == "x_hazard"


def test_walking_through_the_boot_tree(client):
    start(client, "laptop shows a blue screen")
    assert tree.get_node(_current(client))["type"] == "question"

    _answer(client, "0")                                   # a blue screen
    assert _current(client) == "w_unplug"

    html = _answer(client, "not_fixed")
    assert _current(client) == "w_recovery"
    assert "Take care" in html and "Before you start" in html and "Working on updates" in html

    html = _answer(client, "fixed")                        # the recovery menu opened
    assert _current(client) == "w_repair"
    assert "Run Startup Repair" in html

    _answer(client, "fixed")
    assert _current(client) == "w_done_repair"


def test_the_recovery_menu_not_opening_goes_to_a_technician(client):
    start(client, "laptop shows a blue screen")
    for choice in ("0", "not_fixed", "not_fixed"):
        _answer(client, choice)
    assert _current(client) == "w_pro_nostart"


def test_a_screen_that_is_black_with_lights_moves_to_the_display_tree(client):
    start(client, "laptop shows a blue screen")
    html = _answer(client, "4")
    assert _current(client) == "d_start"
    with client.session_transaction() as browser_session:
        assert browser_session["ts"]["category"] == "display"
    assert "blank screen" in html


def test_a_computer_that_does_not_turn_on_moves_to_the_battery_tree(client):
    start(client, "laptop shows a blue screen")
    _answer(client, "5")
    assert _current(client) == "c_start"


def test_random_blue_screens_check_recent_changes_then_heat_then_memory(client):
    start(client, "laptop shows a blue screen")
    _answer(client, "3")
    assert _current(client) == "w_recent"
    _answer(client, "not_fixed")
    assert _current(client) == "w_heat"
    _answer(client, "not_fixed")
    assert _current(client) == "w_mem"
    html = page(client)
    assert "Windows Memory Diagnostic" in html
    _answer(client, "1")                                    # it found memory problems
    assert _current(client) == "w_pro_memory"


def _current(client):
    with client.session_transaction() as browser_session:
        return browser_session["ts"]["node"]
