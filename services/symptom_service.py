"""Normalization: turn the many ways people name a device or a problem into one standard value.

"cp", "cellphone", "selpon" and "my android" all mean the same device type, and "wala'y internet"
and "no net" are the same problem. This module holds those mappings so the rest of the app only
ever sees standard values. It is used in two places:
  - to check and fill in what the AI says about the device, and
  - as the keyword fallback when the AI is off, so Filipino and Bisaya wording still works.

It never chooses troubleshooting steps. That stays with the decision trees.
"""
import re

from services import decision_tree_service as tree

UNKNOWN = "unknown"
DEVICE_LABELS = {
    "computer": "Computer",
    "mobile": "Mobile phone",
    "tablet": "Tablet",
    "networking": "Router / network device",
    "printer": "Printer",
    "electronics": "Electronics / microcontroller",
    "other": "Other",
}
DEVICE_TYPES = tuple(DEVICE_LABELS)

# Below this the app asks the user instead of guessing (see safety_service.apply_confidence).
LOW_CONFIDENCE = 0.5

# Whole-word (or whole-phrase) aliases. When a text names several devices ("my phone cannot
# reach the router") the one mentioned first wins, because it is usually what is broken.
_DEVICE_ALIASES = {
    "mobile": (
        "cp", "cellphone", "cell phone", "celphone", "cellular phone", "mobile phone", "mobile",
        "smartphone", "smart phone", "phone", "selpon", "selfon", "android", "iphone", "ios",
    ),
    "tablet": ("tablet", "ipad", "galaxy tab"),
    "computer": (
        "laptop", "notebook", "desktop", "pc", "computer", "kompyuter", "cpu", "windows",
        "macbook", "chromebook", "all-in-one",
    ),
    "networking": (
        "router", "modem", "wifi router", "wi-fi router", "access point", "range extender",
        "wifi extender", "repeater",
    ),
    "printer": ("printer", "inkjet", "laserjet", "thermal printer"),
    "electronics": (
        "arduino", "esp32", "esp8266", "raspberry pi", "microcontroller", "breadboard", "servo",
    ),
}
_DEVICE_REGEXES = {
    device: re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(a) for a in aliases) + r")(?![\w])", re.IGNORECASE)
    for device, aliases in _DEVICE_ALIASES.items()
}

# Extra problem words the English keywords in the decision trees do not cover.
# Matched from the start of a word, like tree.detect_category.
_LOCAL_KEYWORDS = {
    "battery": ["baterya", "bateria", "lowbat", "nagcharge", "nagcha-charge", "magcharge", "mag-charge",
                "nauubos", "maubos", "naubos"],
    "network": ["walang internet", "wala internet", "walay internet", "walang net", "wala net", "walay net"],
    "audio": ["tunog", "walang tunog", "walay tunog", "dungog"],
    "display": ["blanko", "blangko", "mitim", "nag-black"],
    "storage": ["napuno", "puno na", "walang space", "wala nang space", "kulang sa space"],
    "usb": ["flashdrive", "flashdisk", "flash-drive"],
    "boot": ["asul na screen", "ayaw mag-on", "ayaw mag on", "ayaw magon", "hindi mag-on", "dili mo-on",
             "dili mag-on", "ayaw mag-boot", "nagre-restart", "nag-restart", "nagrestart", "mirestart",
             "mi-restart", "restart ng restart"],
    "performance": ["mabagal", "bagal", "hinay", "naghang", "nagfreeze", "nag-freeze"],
}


def detect_devices(text):
    """Every standard device type named in free text, in the order they are first mentioned."""
    text = (text or "").replace("_", " ")
    hits = []
    for device, regex in _DEVICE_REGEXES.items():
        match = regex.search(text)
        if match:
            hits.append((match.start(), device))
    return [device for _, device in sorted(hits)]


def detect_device(text):
    """The standard device type named first in free text, or 'unknown'."""
    named = detect_devices(text)
    return named[0] if named else UNKNOWN


def device_hint(text):
    """The device type to suggest to the AI: only when the user's words name exactly one kind."""
    named = detect_devices(text)
    return named[0] if len(named) == 1 else None


def reconcile_device(ai_type, text):
    """Combine the AI's device type with the user's own words. Returns (device_type, overridden).

    The user's words win when they name exactly one kind of device and the AI disagrees
    ("cp" is a phone, whatever the AI thinks). When several devices are named, or none, the AI's
    judgement stands, and the words only fill in a gap if the AI said 'unknown'.
    """
    named = detect_devices(text)
    if len(named) == 1 and ai_type != named[0]:
        return named[0], True
    if ai_type == UNKNOWN and named:
        return named[0], False
    return ai_type, False


def normalize_device(value):
    """Map whatever the AI (or a user) wrote for a device to a standard type, or 'unknown'."""
    if not isinstance(value, str):
        return UNKNOWN
    cleaned = value.strip().lower().replace(" ", "_")
    if cleaned in DEVICE_TYPES:
        return cleaned
    if cleaned in ("mobile_device", "smartphone", "phone", "mobile_phone"):
        return "mobile"
    return detect_device(value)


def clean_confidence(value):
    """A confidence as a float from 0 to 1, or None if it is missing or not a number.

    Accepts 0.91, "0.91", 91 and "91%" because models are not consistent about it.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().rstrip("%").strip()
        try:
            number = float(text)
        except ValueError:
            return None
        if value.strip().endswith("%"):
            number /= 100
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        return None
    if number > 1:  # 91 meant 91%
        number /= 100
    if number != number or number < 0 or number > 1:  # NaN or out of range
        return None
    return round(number, 2)


def local_category(text):
    """Category from Filipino/Bisaya problem words, or 'unknown'."""
    text = (text or "").lower()
    scores = {
        cat: sum(1 for k in words if re.search(r"\b" + re.escape(k), text))
        for cat, words in _LOCAL_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else UNKNOWN


def detect_category(text):
    """Keyword fallback used when the AI is off: the English keywords first, then local words."""
    category = tree.detect_category(text)
    return category if category != UNKNOWN else local_category(text)
