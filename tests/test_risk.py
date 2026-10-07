"""Risk level of troubleshooting steps: validated at startup and shown to the user."""
import pytest

from services import decision_tree_service as tree

# Steps that change something on the computer, delete data or involve touching hardware.
MEDIUM_STEPS = {
    "a_service", "r_spooler", "a_driver", "b_driver", "k_driver", "u_devmgr", "c_driver",
    "n_adapter", "r_driver", "u_disk", "s_sense", "p_space", "s_big", "c_port", "k_kb_clean", "p_vent",
    "w_recovery", "w_repair", "w_update", "w_restore", "w_recent", "w_heat",
}


def _category(**step_extra):
    return {
        "category": "demo", "label": "Demo", "prefix": "z_", "pick_label": "Demo", "keywords": ["demo"],
        "start": "z_s",
        "nodes": {
            "z_s": {"type": "step", "title": "t", "do": "d", "why": "w", "expect": "e",
                    "fixed": "z_ok", "not_fixed": "z_esc", **step_extra},
            "z_ok": {"type": "resolved", "cause": "c", "learn": "l"},
            "z_esc": {"type": "escalate", "reason": "r", "causes": ["x"]},
        },
    }


def _build(**step_extra):
    return tree.build_knowledge_base([_category(**step_extra)])


# --- the loader ---------------------------------------------------------------------------------

def test_a_step_without_risk_is_low_risk_and_valid():
    _build()


def test_medium_step_with_a_caution_is_valid():
    _build(risk="medium", caution="Type it exactly as shown.")


@pytest.mark.parametrize("extra", [
    {"risk": "medium"},
    {"risk": "medium", "caution": "   "},
    {"risk": "medium", "caution": 5},
])
def test_medium_step_needs_a_caution(extra):
    with pytest.raises(tree.TreeError, match="caution"):
        _build(**extra)


def test_unknown_risk_level_is_rejected():
    with pytest.raises(tree.TreeError, match="risk must be one of"):
        _build(risk="extreme")


@pytest.mark.parametrize("extra", [
    {"risk": "high", "caution": "careful"},
    {"requires_professional": True},
    {"risk": "medium", "caution": "careful", "requires_professional": True},
])
def test_high_risk_or_professional_only_work_cannot_be_a_guided_step(extra):
    with pytest.raises(tree.TreeError, match="escalate node"):
        _build(**extra)


def test_requires_professional_must_be_a_real_boolean():
    with pytest.raises(tree.TreeError, match="true or false"):
        _build(requires_professional="yes")


# --- the real knowledge base -------------------------------------------------------------------

def _steps():
    return {nid: n for nid, n in tree.TREE.items() if n["type"] == "step"}


def test_the_expected_steps_are_marked_medium():
    medium = {nid for nid, n in _steps().items() if n.get("risk") == "medium"}
    assert medium == MEDIUM_STEPS


def test_every_medium_step_has_a_caution_and_no_step_is_high_risk():
    for nid, node in _steps().items():
        assert node.get("risk", "low") in ("low", "medium"), nid
        assert not node.get("requires_professional"), nid
        if node.get("risk") == "medium":
            assert node["caution"].strip(), nid


def test_every_step_that_runs_a_command_is_at_least_medium_risk():
    for nid, node in _steps().items():
        if node.get("command"):
            assert node.get("risk") == "medium", f"{nid} runs a command but is not marked medium risk"


# --- what the user sees ------------------------------------------------------------------------

def _open_step(client, node_id, category):
    with client.session_transaction() as browser_session:
        browser_session["ts"] = {
            "problem": "test", "category": category, "node": node_id,
            "history": [], "db_id": None, "analysis": None,
        }
    return client.get("/troubleshoot/interview").get_data(as_text=True)


def test_medium_step_shows_take_care_and_the_caution(client):
    html = _open_step(client, "a_service", "audio")
    assert "Take care" in html
    assert "Before you start:" in html and "Type it exactly as shown and nothing else." in html


def test_low_step_shows_low_risk_and_no_caution_box(client):
    html = _open_step(client, "a_volume", "audio")
    assert "Low risk" in html
    assert "Before you start:" not in html
