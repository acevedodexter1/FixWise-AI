"""Checks every AI reply before the app uses it. The AI never controls the troubleshooting steps."""
import re

from services import symptom_service

WARNING = "These are possible causes only and must be verified. FixWise AI cannot inspect your device."
PRIORITIES = ("Low", "Medium", "High")
_CERTAIN = re.compile(
    r"\b(definitely|certainly|for sure|guaranteed|100%)\b|"
    r"\b(is|are|has)\s+(completely\s+|totally\s+)?(broken|dead|defective|faulty|damaged|failed)\b",
    re.IGNORECASE,
)

# What the user types is checked BEFORE any troubleshooting or AI call.
_HAZARD = re.compile(
    r"smok(e|ing)|burn(ing|t)?\s+smell|smells?\s+(like\s+)?(burn|burnt|burning|smoke|plastic)|"
    r"(swollen|bulging|puffed)\s+(up\s+)?battery|battery\s+(is\s+|looks\s+)?(swollen|bulging|puffed)|"
    r"\bsparks?\b|\bmelted\b|on fire|caught fire|"
    r"\bspill(ed|s)?\b|liquid damage|\b(water|coffee|juice|drink)\s+(got|went|poured)\b",
    re.IGNORECASE,
)
_OUT_OF_SCOPE = re.compile(
    r"solder|reflow|reball|bios\s+chip|chip[- ]?level|component[- ]?level|board[- ]?level|"
    r"(repair|fix|replace|rewire|short|test|open|dismantle)\w*\W+(?:\w+\W+){0,4}?"
    r"(motherboard|mainboard|\bpcb\b|circuit\s*board|capacitors?|power\s+supply|\bpsu\b)",
    re.IGNORECASE,
)

# --- Filipino / Taglish / Bisaya wording --------------------------------------------------
# People describe a hazard in their own language ("amoy sunog", "namamaga ang battery",
# "natapunan ng kape"). If these slip past the English patterns above, the user would be
# walked through normal steps for a dangerous situation, so they are checked the same way:
# before any troubleshooting or AI call. A false alarm only sends the user to a technician,
# which is the safe direction to be wrong in.
_DEVICE_WORD = r"(?:laptop|cp|phone|cellphone|celphone|smartphone|keyboard|computer|pc|charger|battery|baterya|tablet)"
_BATTERY = r"(?:bat+er\w*|batt)"  # battery, baterya, bateria
_SWOLLEN = r"(?:namamaga|namaga|nagmamaga|umumbok|umbok|bumubukol|nabukol|bukol|mihubag|nahubag|naghubag|hubag|bloated|puffy)"
_HAZARD_LOCAL = re.compile(
    # smoke
    r"\busok\b|\bumuusok\b|\bnag-?usok\b|\bnaguusok\b|\bnag-?aso\b|\bnaga-?aso\b|\b[mn]i-?aso\b|\bmo-?aso\b|"
    r"\b(?:naa?y|may|adunay)\s+aso\b|"
    # fire / burnt (sunog = fire/burnt, kalayo = fire in Bisaya)
    r"\bsunog\b|\b(?:na|nag|gi)-?sunog\b|\bnasusunog\b|\bsinunog\b|\bapoy\b|\bliyab\b|\bnagliyab\b|\bsumiklab\b|"
    r"\bkalayo\b|\bnagdilaab\b|\bdilaab\b|"
    # burnt / plastic / electrical smell
    r"\b(?:amoy|baho|aroma|naamoy)\W+(?:\w+\W+){0,2}?(?:sunog|plastik|plastic|goma|kuryente|usok)\b|"
    # swollen battery, in either word order
    rf"{_SWOLLEN}\W+(?:\w+\W+){{0,5}}?{_BATTERY}\b|{_BATTERY}\b\W+(?:\w+\W+){{0,5}}?{_SWOLLEN}|"
    # sparks and electric shock
    r"\bnag-?sp[ae]rk\w*|\bsparking\b|short[- ]?circuit|\bnag-?short\b|\bna-?kuryente\b|\bkuryente\s+ako\b|"
    r"electric(?:al)?\s+shock|electrocuted|\bshocked\s+me\b|"
    # liquid: unambiguous words first. "nabasa" also means "read", so it needs a device/liquid nearby
    r"\bnatapunan\b|\bnatapon\b\W+(?:\w+\W+){0,3}?(?:tubig|kape|juice|gatas|softdrinks?|sabaw)|"
    r"\bnabuhusan\b|\bnabasaan\b|\bnalubog\b|\bnalunod\b|\bnalumos\b|\bnatagak\b|"
    r"\bnahulog\W+(?:\w+\W+){0,3}?(?:tubig|banyo|inidoro|toilet|dagat|ilog|sapa)|"
    r"\bnatumba\W+(?:\w+\W+){0,3}?(?:tubig|kape|juice|gatas)|"
    rf"\bnabasa\W+(?:ng|ang|akong|among|iyang)\W+(?:\w+\W+){{0,3}}?(?:tubig|ulan|kape|{_DEVICE_WORD})\b|"
    rf"\b{_DEVICE_WORD}\W+(?:\w+\W+){{0,2}}?nabasa\b(?!\W+(?:ko|mo|niya|namin|nako)\b)|"
    # English gaps
    r"water[- ]damage|got\s+wet|fell\s+(?:in|into)\s+(?:the\s+)?water",
    re.IGNORECASE,
)
# Fix/replace/open verbs in Tagalog and Bisaya, next to a part we never guide repairs on.
_OUT_OF_SCOPE_LOCAL = re.compile(
    r"\b(?:ayusin|ayuhin|ayohon|ayuhon|usbon|kumpunihin|kukumpunihin|palitan|ilisan|ilis|buksan|bubuksan|abrihan|"
    r"tanggalin|baklasin|hiwalayin|pwede\s+bang\s+ayusin)\b\W+(?:\w+\W+){0,4}?"
    r"(?:motherboard|mainboard|\bpcb\b|circuit\s*board|capacitors?|power\s+supply|\bpsu\b)",
    re.IGNORECASE,
)


def check_request(text):
    """Return the id of a professional-referral node if the request must skip troubleshooting."""
    if _HAZARD.search(text) or _HAZARD_LOCAL.search(text):
        return "x_hazard"
    if _OUT_OF_SCOPE.search(text) or _OUT_OF_SCOPE_LOCAL.search(text):
        return "x_scope"
    return None


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    if _CERTAIN.search(text):  # never present a guess as a certainty
        return ""
    return text[:limit]


def _text_list(value, max_items, limit):
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = _text(item, limit)
        if text:
            items.append(text)
        if len(items) == max_items:
            break
    return items


def validate_analysis(data, categories):
    """Return a clean analysis dict, or raise ValueError if the AI reply is unusable."""
    if not isinstance(data, dict):
        raise ValueError("The AI reply is not a JSON object")
    category = data.get("category")
    if not isinstance(category, str) or category not in categories:
        category = "unknown"
    priority = data.get("priority")
    device_text = _text(data.get("device"), 40)
    return {
        "category": category,
        "summary": _text(data.get("problem_summary"), 160),
        "device": device_text,
        # whatever the AI wrote for the device is mapped to one standard type
        "device_type": symptom_service.normalize_device(data.get("device_type") or device_text),
        "device_confidence": symptom_service.clean_confidence(data.get("device_confidence")),
        "category_confidence": symptom_service.clean_confidence(data.get("category_confidence")),
        "low_confidence": False,
        "symptoms": _text_list(data.get("symptoms"), 4, 50),
        "possible_causes": _text_list(data.get("possible_causes"), 4, 60),
        "priority": priority if priority in PRIORITIES else "Medium",
        "warning": WARNING,  # always our own wording, never the AI's
    }


def apply_confidence(analysis, threshold=symptom_service.LOW_CONFIDENCE):
    """If the AI is not confident about the category, ask the user instead of guessing.

    Setting the category to 'unknown' sends the user to the "which sounds closest?" question.
    A missing confidence is not treated as low, so older or simpler AI replies keep working.
    """
    confidence = analysis.get("category_confidence")
    if analysis["category"] != "unknown" and confidence is not None and confidence < threshold:
        analysis["category"] = "unknown"
        analysis["low_confidence"] = True
    return analysis


def empty_analysis(category, device_type="unknown"):
    """Used when the AI is off or failed: only the category from keyword matching."""
    return {
        "category": category,
        "device": "",
        "device_type": device_type,
        "device_confidence": None,
        "category_confidence": None,
        "low_confidence": False,
        "summary": "",
        "symptoms": [],
        "possible_causes": [],
        "priority": "Medium",
        "warning": WARNING,
        "source": "keywords",
        "raw": "",
    }
    


def validate_lesson(data):
    """Clean a 'Teach Me' lesson from the AI, or raise ValueError if it is unusable."""
    if not isinstance(data, dict):
        raise ValueError("The AI reply is not a JSON object")
    lesson = {
        "what_happened": _text(data.get("what_happened"), 400),
        "component": _text(data.get("component"), 200),
        "about_the_steps": _text(data.get("about_the_steps"), 400),
        "prevention": _text_list(data.get("prevention"), 3, 160),
        "related_concepts": _text_list(data.get("related_concepts"), 4, 60),
    }
    if not lesson["what_happened"]:
        raise ValueError("The lesson is empty")
    return lesson