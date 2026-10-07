"""Known error messages: knowledge/error_cases/*.json.

Each case describes one familiar error message or code, which troubleshooting area it
belongs to, what it usually means and its possible causes (never stated as certain).
It is how the screenshot analyzer still works when the AI is switched off, and it is
checked first because a curated match is more reliable than a model's guess.

Like the decision trees, the files are validated when the app starts, so a typo fails
fast instead of breaking a user's session.
"""
import json
import re
from pathlib import Path

from services import decision_tree_service as tree

CASES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "error_cases"
CASE_FIELDS = ("id", "title", "patterns", "category", "meaning", "causes")
# Optional: "generic": true marks a vague message (e.g. "not responding") that fits many areas.
# For those the AI's or the keywords' category is trusted first.
MIN_PATTERN_LENGTH = 6  # shorter patterns would match ordinary words


class KnowledgeError(ValueError):
    """An error-case file is invalid."""


def _validate_case(case, where, seen_ids):
    if not isinstance(case, dict):
        raise KnowledgeError(f"{where}: every case must be an object")
    for field in CASE_FIELDS:
        if not case.get(field):
            raise KnowledgeError(f"{where}: case is missing '{field}'")
    if case["id"] in seen_ids:
        raise KnowledgeError(f"{where}: duplicate case id '{case['id']}'")
    seen_ids.add(case["id"])
    if case["category"] not in tree.START_NODES or case["category"] == "unknown":
        raise KnowledgeError(f"{case['id']}: unknown category '{case['category']}'")
    for field in ("patterns", "causes"):
        if not isinstance(case[field], list) or not all(isinstance(x, str) and x.strip() for x in case[field]):
            raise KnowledgeError(f"{case['id']}: '{field}' must be a list of non-empty text")
    for pattern in case["patterns"]:
        if len(pattern.strip()) < MIN_PATTERN_LENGTH:
            raise KnowledgeError(f"{case['id']}: pattern {pattern!r} is too short to be safe")


def build_error_cases(files):
    """Validate case files (dicts with a 'cases' list) and return a flat list of ready cases."""
    cases, seen_ids = [], set()
    for where, data in files:
        if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
            raise KnowledgeError(f"{where}: expected an object with a 'cases' list")
        for case in data["cases"]:
            _validate_case(case, where, seen_ids)
            cases.append({
                **case,
                "_regexes": [
                    re.compile(r"(?<!\w)" + re.escape(" ".join(p.lower().split())) + r"(?!\w)")
                    for p in case["patterns"]
                ],
            })
    return cases


def load_error_cases(directory=CASES_DIR):
    files = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            files.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as error:
            raise KnowledgeError(f"{path.name}: {error}") from error
    return build_error_cases(files)


ERROR_CASES = load_error_cases()


def match_error(text, cases=None):
    """The best known error case for this text, or None.

    The case with the longest matching pattern wins, because a longer pattern is more specific.
    """
    text = " ".join((text or "").lower().split())
    best, best_length = None, 0
    for case in cases if cases is not None else ERROR_CASES:
        for pattern, regex in zip(case["patterns"], case["_regexes"]):
            if len(pattern) > best_length and regex.search(text):
                best, best_length = case, len(pattern)
    return best


def public(case):
    """The case without its compiled regexes (safe to show or serialise)."""
    return {k: v for k, v in case.items() if not k.startswith("_")}
