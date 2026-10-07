import io

import pytest

from conftest import page
from services import ai_service, knowledge_service, screenshot_service
from services import decision_tree_service as tree

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
CATEGORIES = {k: v for k, v in tree.CATEGORY_LABELS.items() if k != "unknown"}


def _upload(client, data=PNG, name="shot.png", text=""):
    body = {"error_text": text}
    if data is not None:
        body["screenshot"] = (io.BytesIO(data), name)
    return client.post("/troubleshoot/screenshot", data=body, content_type="multipart/form-data")


def _ai_on(client, monkeypatch, analysis=None, fail=False):
    """Switch the AI on and replace the model call, so tests never touch the network."""
    client.application.config["AI_API_KEY"] = "test-key"
    calls = []

    def fake(image, note, categories):
        calls.append((image, note))
        if fail:
            raise RuntimeError("model does not accept images")
        return analysis

    monkeypatch.setattr(screenshot_service, "read_with_ai", fake)
    yield_calls = calls
    return yield_calls


@pytest.fixture(autouse=True)
def _reset_ai(client):
    yield
    client.application.config["AI_API_KEY"] = ""


def _analysis(error_text="DNS_PROBE_FINISHED_NO_INTERNET", category="network"):
    return {
        "category": category, "summary": "No internet", "symptoms": [], "possible_causes": [],
        "priority": "Medium", "warning": "", "error_text": error_text,
    }


# ---------- file checks ----------

@pytest.mark.parametrize("data, expected", [
    (b"\x89PNG\r\n\x1a\nrest", "image/png"),
    (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    (b"GIF89a", None),
    (b"<svg onload=alert(1)>", None),
    (b"%PDF-1.7", None),
    (b"", None),
])
def test_sniff_image_uses_the_real_bytes(data, expected):
    assert screenshot_service.sniff_image(data) == expected


def test_page_without_ai_only_offers_typing(client):
    html = page(client, "/troubleshoot/screenshot")
    assert "Check an error message" in html
    assert 'type="file"' not in html
    assert "AI feature, which is off" in html


def test_page_with_ai_offers_upload_and_privacy_note(client):
    client.application.config["AI_API_KEY"] = "test-key"
    html = page(client, "/troubleshoot/screenshot")
    assert 'type="file"' in html
    assert "not saved on this site" in html


def test_empty_submit_is_refused(client):
    html = _upload(client, data=None).get_data(as_text=True)
    assert "Upload a screenshot or type the error message" in html


def test_fake_image_is_refused_even_with_a_png_name(client):
    html = _upload(client, data=b"<?php echo 1; ?>", name="evil.png").get_data(as_text=True)
    assert "Upload a PNG, JPG or WebP screenshot" in html


def test_empty_file_is_refused(client):
    html = _upload(client, data=b"", name="empty.png").get_data(as_text=True)
    assert "That file is empty" in html


def test_too_large_upload_gets_a_clear_413(client):
    client.application.config["MAX_CONTENT_LENGTH"] = 1024
    try:
        response = _upload(client, data=PNG + b"x" * 5000)
    finally:
        client.application.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    assert response.status_code == 413
    assert "larger than" in response.get_data(as_text=True)


# ---------- typed error text (works with the AI off) ----------

def test_typed_known_error_is_recognised_and_prefilled(client):
    html = _upload(client, data=None, text="DNS_PROBE_FINISHED_NO_INTERNET").get_data(as_text=True)
    assert "Website address could not be found" in html
    assert "Possible causes (not confirmed)" in html
    assert 'name="category_hint" value="network"' in html
    assert "DNS_PROBE_FINISHED_NO_INTERNET</textarea>" in html


def test_unknown_error_still_lets_the_user_continue(client):
    html = _upload(client, data=None, text="Something odd happened 0xDEADBEEF").get_data(as_text=True)
    assert "do not recognise this error yet" in html
    assert "Start troubleshooting" in html


def test_image_without_ai_explains_and_does_not_crash(client):
    html = _upload(client).get_data(as_text=True)
    assert "needs the AI feature" in html
    assert "Start troubleshooting" not in html


def test_text_from_the_screenshot_is_escaped(client, monkeypatch):
    _ai_on(client, monkeypatch, _analysis(error_text="<script>alert(1)</script> usb device not recognized"))
    html = _upload(client).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ---------- with the AI on ----------

def test_ai_reads_the_screenshot_and_the_result_is_shown(client, monkeypatch):
    calls = _ai_on(client, monkeypatch, _analysis())
    html = _upload(client).get_data(as_text=True)
    assert len(calls) == 1 and calls[0][0][0] == "image/png"
    assert "Error on the screen" in html and "Website address could not be found" in html


def test_ai_failure_falls_back_to_a_message_and_typed_text_still_works(client, monkeypatch):
    _ai_on(client, monkeypatch, fail=True)
    html = _upload(client, text="printer is offline").get_data(as_text=True)
    assert "could not read that screenshot" in html
    assert "Printer is offline" in html  # the typed text was still looked up


def test_ai_limit_per_visit_is_enforced(client, monkeypatch):
    calls = _ai_on(client, monkeypatch, _analysis())
    with client.session_transaction() as s:
        s["shots_made"] = screenshot_service.MAX_AI_SCREENSHOTS_PER_VISIT
    html = _upload(client).get_data(as_text=True)
    assert calls == []
    assert "limit for this visit" in html


def test_each_ai_attempt_counts_even_when_it_fails(client, monkeypatch):
    _ai_on(client, monkeypatch, fail=True)
    _upload(client)
    with client.session_transaction() as s:
        assert s["shots_made"] == 1


# ---------- category choice ----------

def test_specific_known_error_beats_the_ai_category(client):
    client.application.config["AI_API_KEY"] = ""
    with client.application.app_context():
        result = screenshot_service.analyze(None, "Printer is offline", CATEGORIES)
    assert result["category"] == "printer"


def test_vague_known_error_defers_to_the_ai(client, monkeypatch):
    client.application.config["AI_API_KEY"] = "test-key"
    monkeypatch.setattr(screenshot_service, "read_with_ai",
                        lambda *a: _analysis(error_text="printer not responding", category="printer"))
    with client.application.app_context():
        result = screenshot_service.analyze(("image/png", PNG), "", CATEGORIES)
    assert result["match"]["generic"] is True
    assert result["category"] == "printer"  # not "performance"


# ---------- handing over to the normal flow ----------

def test_category_hint_is_used_only_when_nothing_else_knows(client):
    client.post("/troubleshoot", data={"problem": "Error 0xDEADBEEF appeared", "category_hint": "network"})
    with client.session_transaction() as s:
        assert s["ts"]["category"] == "network"


def test_category_hint_does_not_override_a_clear_problem(client):
    client.post("/troubleshoot", data={"problem": "my wifi has no internet", "category_hint": "printer"})
    with client.session_transaction() as s:
        assert s["ts"]["category"] == "network"


def test_forged_category_hint_is_ignored(client):
    client.post("/troubleshoot", data={"problem": "Error 0xDEADBEEF appeared", "category_hint": "../../etc"})
    with client.session_transaction() as s:
        assert s["ts"]["category"] == "unknown"


def test_safety_rules_still_apply_to_text_from_a_screenshot(client):
    client.post("/troubleshoot", data={"problem": "Error shown on screen: battery is swollen", "category_hint": "battery"})
    html = page(client)
    assert "Professional assistance recommended" in html


# ---------- the AI call itself ----------

def test_vision_call_sends_the_image_and_the_vision_model(client, monkeypatch):
    sent = {}

    class FakeCompletions:
        def create(self, **kwargs):
            sent.update(kwargs)
            message = type("M", (), {"content": "{}"})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", FakeClient)
    client.application.config.update(AI_API_KEY="k", AI_MODEL="text-model", AI_VISION_MODEL="vision-model")
    with client.application.app_context():
        ai_service._call_model("system", "note", image=("image/png", b"abc"), model="vision-model")
    parts = sent["messages"][1]["content"]
    assert sent["model"] == "vision-model"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    client.application.config.update(AI_MODEL="", AI_VISION_MODEL="")


def _sent_for(client, monkeypatch, model, image=None):
    sent = {}

    class FakeCompletions:
        def create(self, **kwargs):
            sent.update(kwargs)
            message = type("M", (), {"content": "{}"})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", FakeClient)
    client.application.config.update(AI_API_KEY="k", AI_MODEL="", AI_VISION_MODEL="")
    with client.application.app_context():
        ai_service._call_model("system", "note", image=image, model=model)
    return sent


def test_qwen_runs_in_instruct_mode_so_thinking_cannot_eat_the_answer(client, monkeypatch):
    sent = _sent_for(client, monkeypatch, "qwen/qwen3.8-27b", image=("image/png", b"abc"))
    assert sent["extra_body"] == {"reasoning_effort": "none"}
    assert sent["max_tokens"] >= 2000


def test_gpt_oss_keeps_low_reasoning_and_other_models_get_no_extras(client, monkeypatch):
    assert _sent_for(client, monkeypatch, "openai/gpt-oss-20b")["extra_body"] == {"reasoning_effort": "low"}
    assert _sent_for(client, monkeypatch, "some-other-model")["extra_body"] is None


def test_text_only_call_is_unchanged(client, monkeypatch):
    sent = {}

    class FakeCompletions:
        def create(self, **kwargs):
            sent.update(kwargs)
            message = type("M", (), {"content": "{}"})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()]})()

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("openai.OpenAI", FakeClient)
    client.application.config.update(AI_API_KEY="k", AI_MODEL="text-model")
    with client.application.app_context():
        ai_service._call_model("system", "my wifi is slow")
    assert sent["model"] == "text-model"
    assert isinstance(sent["messages"][1]["content"], str)
    client.application.config.update(AI_MODEL="")


# ---------- the error-case knowledge files ----------

def _case(**overrides):
    case = {"id": "t1", "title": "T", "patterns": ["some error text"], "category": "network",
            "meaning": "M", "causes": ["C"]}
    case.update(overrides)
    return case


def test_real_error_cases_are_valid():
    assert len(knowledge_service.ERROR_CASES) >= 20
    for case in knowledge_service.ERROR_CASES:
        assert case["category"] in tree.START_NODES


@pytest.mark.parametrize("bad, message", [
    (_case(category="warp"), "unknown category"),
    (_case(patterns=["usb"]), "too short"),
    (_case(causes=[]), "missing 'causes'"),
    (_case(meaning=""), "missing 'meaning'"),
    (_case(patterns=[""]), "non-empty"),
])
def test_bad_error_cases_are_rejected(bad, message):
    with pytest.raises(knowledge_service.KnowledgeError, match=message):
        knowledge_service.build_error_cases([("f.json", {"cases": [bad]})])


def test_duplicate_case_id_is_rejected():
    with pytest.raises(knowledge_service.KnowledgeError, match="duplicate"):
        knowledge_service.build_error_cases([("f.json", {"cases": [_case(), _case()]})])


def test_longest_pattern_wins_and_words_are_whole():
    cases = knowledge_service.build_error_cases([("f.json", {"cases": [
        _case(id="a", patterns=["no signal"]),
        _case(id="b", patterns=["no signal detected on hdmi"], category="display"),
    ]})])
    assert knowledge_service.match_error("Monitor: NO SIGNAL detected on HDMI 1", cases)["id"] == "b"
    assert knowledge_service.match_error("no signals today", cases) is None
    assert knowledge_service.match_error("", cases) is None