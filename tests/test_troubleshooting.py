import copy

import pytest

from conftest import page, start
from services import decision_tree_service as tree


CATEGORIES = ["display", "network", "audio", "performance", "usb", "printer",
              "input", "bluetooth", "battery", "storage"]


def _category(**overrides):
    data = {
        "category": "demo", "label": "Demo", "prefix": "z_", "pick_label": "Demo problem",
        "keywords": ["demo"], "start": "z_start",
        "nodes": {
            "z_start": {"type": "step", "title": "T", "do": "D", "why": "W", "expect": "E",
                        "fixed": "z_done", "not_fixed": "z_pro"},
            "z_done": {"type": "resolved", "cause": "C", "learn": "L"},
            "z_pro": {"type": "escalate", "reason": "R", "causes": ["X"]},
        },
    }
    data.update(overrides)
    return data


# ---------- the knowledge base itself ----------

def test_real_knowledge_base_is_valid():
    assert set(CATEGORIES) <= set(tree.START_NODES)
    assert "x_hazard" in tree.TREE and "x_scope" in tree.TREE
    for start_node in tree.START_NODES.values():
        assert tree.steps_remaining(start_node) > 0


def test_valid_category_builds():
    built, starts, labels, _, _ = tree.build_knowledge_base([_category()])
    assert starts["demo"] == "z_start" and labels["demo"] == "Demo"
    assert built["pick"]["options"][0]["next"] == "z_start"


def test_missing_target_is_rejected():
    data = _category()
    data["nodes"]["z_start"]["not_fixed"] = "z_nowhere"
    with pytest.raises(tree.TreeError, match="missing node"):
        tree.build_knowledge_base([data])


def test_loop_is_rejected():
    data = _category()
    data["nodes"]["z_second"] = {"type": "step", "title": "T", "do": "D", "why": "W", "expect": "E",
                                 "fixed": "z_pro", "not_fixed": "z_start"}
    data["nodes"]["z_start"]["not_fixed"] = "z_second"
    with pytest.raises(tree.TreeError, match="loop"):
        tree.build_knowledge_base([data])


def test_unreachable_node_is_rejected():
    data = _category()
    data["nodes"]["z_orphan"] = copy.deepcopy(data["nodes"]["z_done"])
    with pytest.raises(tree.TreeError, match="never be reached"):
        tree.build_knowledge_base([data])


def test_missing_field_and_wrong_prefix_are_rejected():
    data = _category()
    del data["nodes"]["z_start"]["expect"]
    with pytest.raises(tree.TreeError, match="missing 'expect'"):
        tree.build_knowledge_base([data])
    bad = _category(nodes={"a_start": _category()["nodes"]["z_done"]}, start="a_start")
    with pytest.raises(tree.TreeError, match="must start with"):
        tree.build_knowledge_base([bad])


def test_duplicate_prefix_is_rejected():
    with pytest.raises(tree.TreeError, match="already used"):
        tree.build_knowledge_base([_category(), _category(category="other")])


def test_keyword_detection_matches_word_starts():
    assert tree.detect_category("my wifi shows connected but websites won't open") == "network"
    assert tree.detect_category("there is no sound from my speakers") == "audio"
    assert tree.detect_category("I want to change my wallpaper") == "unknown"  # 'change' is not 'hang'


# ---------- guest flow through the routes ----------

def test_guest_resolves_network_problem(client):
    html = start(client, "my wifi shows connected but websites won't open")
    assert "Does your computer say it is connected to Wi-Fi?" in html
    client.post("/troubleshoot/answer", data={"choice": "0"})  # Yes, connected
    client.post("/troubleshoot/answer", data={"choice": "0"})  # other devices work
    assert "ipconfig /flushdns" in page(client)
    client.post("/troubleshoot/answer", data={"choice": "fixed"})
    assert "A temporary DNS problem." in page(client)


def test_already_tried_skips_the_step(client):
    start(client, "there is no sound from my speakers")
    client.post("/troubleshoot/answer", data={"choice": "1"})       # not after plugging anything in
    assert "Check volume and mute" in page(client)
    client.post("/troubleshoot/answer", data={"choice": "tried"})
    html = page(client)
    assert "Choose the correct output device" in html
    assert "Already tried (skipped)" in html


def test_unknown_problem_offers_every_category(client):
    html = start(client, "something feels off today")
    assert "I&#39;m not sure yet" in html or "I'm not sure yet" in html
    for option in tree.TREE["pick"]["options"]:
        assert option["label"].replace("'", "&#39;") in html or option["label"] in html


def test_invalid_choice_does_not_move(client):
    start(client, "there is no sound from my speakers")
    before = page(client)
    client.post("/troubleshoot/answer", data={"choice": "99"})
    assert page(client) == before


def test_post_without_csrf_token_is_rejected(client):
    flask_app = client.application
    flask_app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert client.post("/troubleshoot", data={"problem": "no sound"}).status_code == 400
    finally:
        flask_app.config["WTF_CSRF_ENABLED"] = False


# ---------- every category: a way out and a working fallback ----------

def _walk(category, step_choice):
    """Follow the first option on questions and `step_choice` on steps until the tree ends."""
    node_id = tree.START_NODES[category]
    while tree.TREE[node_id]["type"] in ("question", "step"):
        node = tree.TREE[node_id]
        node_id = node["options"][0]["next"] if node["type"] == "question" else node[step_choice]
    return tree.TREE[node_id]


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_can_end_in_a_fix_or_a_referral(category):
    assert _walk(category, "fixed")["type"] == "resolved"
    assert _walk(category, "not_fixed")["type"] == "escalate"


@pytest.mark.parametrize("text, expected", [
    ("my usb flash drive is not detected", "usb"),
    ("the printer will not print", "printer"),
    ("my mouse is not responding", "input"),
    ("my bluetooth headphones will not pair", "bluetooth"),
    ("my laptop is not charging", "battery"),
    ("my hard drive is almost full", "storage"),
])
def test_keyword_detection_for_new_categories(text, expected):
    assert tree.detect_category(text) == expected


def test_printer_flow_resolves(client):
    html = start(client, "my printer will not print")
    assert "How is the printer connected to your computer?" in html
    client.post("/troubleshoot/answer", data={"choice": "0"})        # USB cable
    assert "Check power, paper and cables" in page(client)
    client.post("/troubleshoot/answer", data={"choice": "fixed"})
    assert "A paper jam, empty tray, low ink or a loose cable." in page(client)


def test_storage_drive_that_may_be_failing_is_referred(client):
    start(client, "my hard drive is making clicking noises")
    client.post("/troubleshoot/answer", data={"choice": "2"})        # slow or clicking
    client.post("/troubleshoot/answer", data={"choice": "1"})        # Warning or Unhealthy
    html = page(client)
    assert "Professional assistance recommended" in html
    assert "Your drive may be failing" in html