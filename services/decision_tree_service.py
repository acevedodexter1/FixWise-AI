"""The troubleshooting knowledge base: decision trees loaded from knowledge/decision_trees/*.json.

To add a category, drop a new JSON file into that folder (copy an existing one for the shape).
Everything is validated when the app starts, so a typo fails fast instead of breaking a
user's session halfway through.

Node types:
  question : options -> next node
  step     : do/why/expect, then "fixed" or "not_fixed" -> next node
  resolved : problem solved, shows cause + what the user learned
  escalate : safe steps exhausted -> professional assistance recommended

Every step also carries a risk level (optional, "low" when left out):
  "low"    : nothing special, shown as is.
  "medium" : safe for a beginner but easy to get wrong (admin commands, deleting files, driver
             changes, cleaning near a port). Needs a "caution" text, shown before the step.
  "high"   : never a guided step. A step marked "high" risk, or "requires_professional": true,
             is refused when the app starts. That work must be an escalate node instead, so a
             typo can never put a dangerous instruction in front of a user.
"""
import json
import re
from pathlib import Path

TREE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "decision_trees"
SHARED_FILE = "_shared.json"  # nodes not tied to one category, e.g. the safety referrals
PICK_NODE = "pick"
TERMINAL = ("resolved", "escalate")
REQUIRED_FIELDS = {
    "question": ("text", "why", "options"),
    "step": ("title", "do", "why", "expect", "fixed", "not_fixed"),
    "resolved": ("cause", "learn"),
    "escalate": ("reason", "causes"),
}
RISK_LEVELS = ("low", "medium", "high")
CATEGORY_FIELDS = ("category", "label", "prefix", "pick_label", "keywords", "start", "nodes")


class TreeError(ValueError):
    """The knowledge base is invalid."""


def _targets(node):
    if node["type"] == "question":
        return [option["next"] for option in node["options"]]
    if node["type"] == "step":
        return [node["fixed"], node["not_fixed"]]
    return []


def _validate_risk(node_id, node):
    risk = node.get("risk", "low")
    if risk not in RISK_LEVELS:
        raise TreeError(f"{node_id}: risk must be one of {', '.join(RISK_LEVELS)}, not {risk!r}")
    professional = node.get("requires_professional", False)
    if not isinstance(professional, bool):
        raise TreeError(f"{node_id}: 'requires_professional' must be true or false")
    if risk == "high" or professional:
        raise TreeError(
            f"{node_id}: a high-risk or professional-only job cannot be a guided step. "
            "Make it an escalate node instead."
        )
    if risk == "medium" and not (isinstance(node.get("caution"), str) and node["caution"].strip()):
        raise TreeError(f"{node_id}: a medium-risk step needs a 'caution' text")


def _validate_nodes(tree):
    for node_id, node in tree.items():
        kind = node.get("type")
        if kind not in REQUIRED_FIELDS:
            raise TreeError(f"{node_id}: unknown node type {kind!r}")
        for field in REQUIRED_FIELDS[kind]:
            if not node.get(field):
                raise TreeError(f"{node_id}: missing '{field}'")
        if kind == "step":
            _validate_risk(node_id, node)
        if kind == "question":
            for option in node["options"]:
                if not isinstance(option, dict) or not option.get("label") or not option.get("next"):
                    raise TreeError(f"{node_id}: every option needs a 'label' and a 'next'")
        for target in _targets(node):
            if target not in tree:
                raise TreeError(f"{node_id} points to a missing node '{target}'")


def _check_reachable(tree, start, own_nodes, category):
    seen, queue = {start}, [start]
    while queue:
        for target in _targets(tree[queue.pop()]):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    orphans = [n for n in own_nodes if n not in seen]
    if orphans:
        raise TreeError(f"{category}: nodes that can never be reached: {', '.join(orphans)}")


def _check_acyclic(tree):
    """A loop would trap a user in the same steps forever and break the progress bar."""
    state = {}  # 1 = on the current path, 2 = finished
    for root in tree:
        if root in state:
            continue
        state[root] = 1
        stack = [(root, iter(_targets(tree[root])))]
        while stack:
            node_id, targets = stack[-1]
            for target in targets:
                if state.get(target) == 1:
                    raise TreeError(f"loop detected: {node_id} -> {target}")
                if target not in state:
                    state[target] = 1
                    stack.append((target, iter(_targets(tree[target]))))
                    break
            else:
                state[node_id] = 2
                stack.pop()


def build_knowledge_base(files, shared_nodes=None):
    """Validate category dicts and return (TREE, START_NODES, CATEGORY_LABELS, KEYWORDS, prefixes)."""
    tree, starts, labels, keywords, prefixes = {}, {}, {}, {}, {}

    def add(node_id, node, where):
        if node_id in tree or node_id == PICK_NODE:
            raise TreeError(f"{where}: duplicate node id '{node_id}'")
        tree[node_id] = node

    for node_id, node in (shared_nodes or {}).items():
        add(node_id, node, "shared nodes")

    own = {}
    for data in sorted(files, key=lambda f: f.get("order", 99)):
        missing = [k for k in CATEGORY_FIELDS if k not in data]
        if missing:
            raise TreeError(f"category file is missing: {', '.join(missing)}")
        key, prefix = data["category"], data["prefix"]
        if key in labels or key == "unknown":
            raise TreeError(f"duplicate category '{key}'")
        if prefix in prefixes:
            raise TreeError(f"{key}: prefix '{prefix}' is already used")
        if data["start"] not in data["nodes"]:
            raise TreeError(f"{key}: start node '{data['start']}' does not exist")
        for node_id, node in data["nodes"].items():
            if not node_id.startswith(prefix):
                raise TreeError(f"{key}: node '{node_id}' must start with '{prefix}'")
            add(node_id, node, key)
        own[key] = list(data["nodes"])
        labels[key], starts[key] = data["label"], data["start"]
        keywords[key], prefixes[prefix] = list(data["keywords"]), key

    if not own:
        raise TreeError("no category files found")

    tree[PICK_NODE] = {
        "type": "question",
        "text": "I'm not sure yet which area this is. Which sounds closest to your problem?",
        "why": "Each area has its own set of safe checks.",
        "options": [
            {"label": d["pick_label"], "next": d["start"]}
            for d in sorted(files, key=lambda f: f.get("order", 99))
        ],
    }
    labels["unknown"], starts["unknown"] = "Not sure yet", PICK_NODE

    _validate_nodes(tree)
    for key, node_ids in own.items():
        _check_reachable(tree, starts[key], node_ids, key)
    _check_acyclic(tree)
    return tree, starts, labels, keywords, prefixes


def load_knowledge_base(directory=TREE_DIR):
    files, shared = [], {}
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise TreeError(f"{path.name}: {error}") from error
        if path.name == SHARED_FILE:
            shared = data.get("nodes", {})
        else:
            files.append(data)
    return build_knowledge_base(files, shared)


TREE, START_NODES, CATEGORY_LABELS, KEYWORDS, _PREFIX = load_knowledge_base()
_cache = {}


def detect_category(text):
    """Keyword fallback used when the AI is off. Matches from the start of a word."""
    text = text.lower()
    # a longer keyword is more specific ("blue screen" beats the common word "screen")
    scores = {
        cat: sum(len(k) for k in kws if re.search(r"\b" + re.escape(k), text))
        for cat, kws in KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def category_of(node_id):
    for prefix, cat in _PREFIX.items():
        if node_id.startswith(prefix):
            return cat
    return None


def get_node(node_id):
    return TREE[node_id]


def steps_remaining(node_id):
    """Longest number of questions/steps still possible from this node (including it)."""
    if node_id in _cache:
        return _cache[node_id]
    node = TREE[node_id]
    if node["type"] in TERMINAL:
        n = 0
    else:
        n = 1 + max(steps_remaining(t) for t in _targets(node))
    _cache[node_id] = n
    return n