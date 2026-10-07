"""The troubleshooting report for a technician: one data structure, three outputs.

build_report() turns a session (saved in the database or still in the browser) into a plain
dict. The on-screen page, as_text() and build_pdf() all render that same dict, so the three
can never disagree with each other.
"""
import re
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services import decision_tree_service as tree
from services import device_service, safety_service

TITLE = "FixWise AI Troubleshooting Report"
MAX_PROBLEM = 1500  # characters of the user's description shown in the report
GUEST_REFERENCE = "Guest session (not saved)"
HARDWARE_NOTE = "For safety, FixWise AI does not provide motherboard-level or electrical repair instructions."

STATUS_LABELS = {
    "ACTIVE": "In progress",
    "RESOLVED": "Resolved",
    "ESCALATED": "Professional help recommended",
    "UNRESOLVED": "Not finished",
}


# ---------- building the report ----------

def reference_for(db_id):
    """Report number for a saved session, e.g. FW-000042. None for a guest."""
    return f"FW-{int(db_id):06d}" if db_id else None


def _stamp(moment):
    return moment.strftime("%b %d, %Y, %I:%M %p")


def _status_from_node(node):
    return {"resolved": "RESOLVED", "escalate": "ESCALATED"}.get(node["type"], "ACTIVE")


def _clean_analysis(analysis):
    """The AI's (or keyword) understanding of the problem. None when there is nothing to show."""
    if not analysis:
        return None
    clean = {
        "summary": analysis.get("summary") or "",
        "symptoms": list(analysis.get("symptoms") or []),
        "possible_causes": list(analysis.get("possible_causes") or []),
        "ai": analysis.get("source") == "ai",
    }
    return clean if (clean["summary"] or clean["symptoms"] or clean["possible_causes"]) else None


def _outcome(status, node):
    if status == "RESOLVED" and node["type"] == "resolved":
        return {
            "kind": "resolved",
            "heading": "Resolved",
            "text": node["cause"] + " This is a likely explanation, not a confirmed finding.",
            "learn": node["learn"],
            "causes": [],
            "hardware": False,
        }
    if status == "ESCALATED" and node["type"] == "escalate":
        return {
            "kind": "escalated",
            "heading": "Professional assistance recommended",
            "text": node["reason"],
            "learn": "",
            "causes": list(node["causes"]),
            "hardware": bool(node.get("hardware")),
        }
    if status == "UNRESOLVED":
        text = "The user started over before this session reached a result."
    else:
        text = "This session is still in progress. The report is more useful once it reaches a result."
    return {"kind": "open", "heading": "Not finished", "text": text, "learn": "", "causes": [], "hardware": False}


def _device_info(device):
    """The device facts for the report: one readable line plus the owner's notes. None for no device."""
    if not device:
        return None
    return {"summary": device_service.summary(device), "notes": (device.get("notes") or "").strip()}


def build_report(problem, category, node, history, status=None, analysis=None,
                 reference=None, started=None, now=None, device=None):
    """Collect everything the report needs.

    node:    the session's current decision-tree node (a result node once it is finished)
    history: [{"text": question or step, "answer": what the user answered}, ...] in order
    device:  the saved device facts (see Device.snapshot) or None
    status:  ACTIVE / RESOLVED / ESCALATED / UNRESOLVED. Worked out from the node if omitted.
    """
    status = status or _status_from_node(node)
    reference = reference or GUEST_REFERENCE
    file_part = reference if reference.startswith("FW-") else "guest"
    return {
        "reference": reference,
        "filename": f"fixwise-report-{file_part}.pdf",
        "generated": _stamp(now or datetime.now()),
        "started": _stamp(started) if started else "",
        "problem": (problem or "").strip()[:MAX_PROBLEM],
        "category": tree.CATEGORY_LABELS.get(category, category or "Not sure yet"),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "analysis": _clean_analysis(analysis),
        "device": _device_info(device),
        "steps": [
            {"number": number, "text": item["text"], "answer": item["answer"]}
            for number, item in enumerate(history, start=1)
        ],
        "outcome": _outcome(status, node),
        "disclaimer": safety_service.WARNING,
    }


# ---------- plain text (the copy button) ----------

def as_text(report):
    lines = [TITLE.upper(), f"Reference: {report['reference']}", f"Generated: {report['generated']}"]
    if report["started"]:
        lines.append(f"Session started: {report['started']}")
    lines += [f"Category: {report['category']}", f"Status: {report['status_label']}"]
    if report["device"]:
        lines.append(f"Device: {report['device']['summary']}")
        if report["device"]["notes"]:
            lines.append(f"Device notes: {report['device']['notes']}")
    lines.append("")

    lines += ["PROBLEM DESCRIBED BY THE USER", report["problem"], ""]

    outcome = report["outcome"]
    lines += [f"OUTCOME: {outcome['heading']}", outcome["text"]]
    if outcome["learn"]:
        lines.append(f"Background: {outcome['learn']}")
    if outcome["causes"]:
        lines += ["Possible causes (not confirmed):"] + [f"- {c}" for c in outcome["causes"]]
    if outcome["hardware"]:
        lines.append(HARDWARE_NOTE)
    lines.append("")

    analysis = report["analysis"]
    if analysis:
        lines.append("WHAT FIXWISE AI UNDERSTOOD" + (" (AI-generated, not verified)" if analysis["ai"] else ""))
        if analysis["summary"]:
            lines.append(analysis["summary"])
        if analysis["symptoms"]:
            lines += ["Symptoms:"] + [f"- {s}" for s in analysis["symptoms"]]
        if analysis["possible_causes"]:
            lines += ["Possible causes (not confirmed):"] + [f"- {c}" for c in analysis["possible_causes"]]
        lines.append("")

    lines.append("QUESTIONS AND STEPS")
    if report["steps"]:
        lines += [f"{s['number']}. {s['text']} -> {s['answer']}" for s in report["steps"]]
    else:
        lines.append("None. The request was referred before any step was tried.")
    lines += ["", f"NOTE: {report['disclaimer']}"]
    return "\n".join(lines)


# ---------- PDF ----------

INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#55607a")
LINE = colors.HexColor("#d5dce8")
PAPER = colors.HexColor("#f2f5f9")
SIGNAL = colors.HexColor("#2457f5")
OUTCOME_COLORS = {
    "resolved": colors.HexColor("#1e9e6a"),
    "escalated": colors.HexColor("#e0a100"),
    "open": MUTED,
}

PAGE_MARGIN = 18 * mm
FRAME_PADDING = 6  # points of padding reportlab adds inside the page frame, on each side
CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN - 2 * FRAME_PADDING

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=INK)
_SMALL = ParagraphStyle("small", parent=_BODY, fontSize=8.5, leading=12, textColor=MUTED)
_BRAND = ParagraphStyle("brand", parent=_BODY, fontName="Helvetica-Bold", fontSize=11, textColor=SIGNAL)
_TITLE = ParagraphStyle("title", parent=_BODY, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=6)
_HEADING = ParagraphStyle(
    "heading", parent=_BODY, fontName="Helvetica-Bold", fontSize=12, leading=15,
    spaceBefore=14, spaceAfter=5, keepWithNext=1,
)
_LABEL = ParagraphStyle("label", parent=_BODY, fontName="Helvetica-Bold", textColor=MUTED)
_HEAD_CELL = ParagraphStyle("head_cell", parent=_BODY, fontName="Helvetica-Bold", fontSize=9, textColor=colors.white)
_BULLET = ParagraphStyle("bullet", parent=_BODY, leftIndent=12, bulletIndent=2, spaceAfter=2)
_OUTCOME_HEAD = ParagraphStyle("outcome_head", parent=_BODY, fontName="Helvetica-Bold", fontSize=12, spaceAfter=4)


def _plain(value):
    """Text for the PDF fonts. The built-in fonts only cover Western European characters,
    so anything else (emoji, other scripts) becomes '?'."""
    text = _CONTROL.sub("", str(value if value is not None else ""))
    return text.encode("cp1252", "replace").decode("cp1252")


def _markup(value):
    """Escape user text so it can never be read as Paragraph markup, and keep its line breaks."""
    text = escape(_plain(value))
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")


def _para(value, style=_BODY):
    return Paragraph(_markup(value), style)


def _bullets(items):
    return [Paragraph(_markup(item), _BULLET, bulletText="\u2022") for item in items]


def _meta_table(report):
    rows = [("Reference", report["reference"]), ("Generated", report["generated"])]
    if report["started"]:
        rows.append(("Session started", report["started"]))
    rows += [("Category", report["category"]), ("Status", report["status_label"])]
    if report["device"]:
        rows.append(("Device", report["device"]["summary"]))
        if report["device"]["notes"]:
            rows.append(("Device notes", report["device"]["notes"]))
    table = Table(
        [[_para(label, _LABEL), _para(value)] for label, value in rows],
        colWidths=[38 * mm, CONTENT_WIDTH - 38 * mm],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _steps_table(steps):
    widths = [10 * mm, 104 * mm, CONTENT_WIDTH - 114 * mm]
    rows = [[_para("#", _HEAD_CELL), _para("Question or step", _HEAD_CELL), _para("Answer or result", _HEAD_CELL)]]
    rows += [[_para(s["number"]), _para(s["text"]), _para(s["answer"])] for s in steps]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _outcome_box(outcome):
    content = [_para(outcome["heading"], _OUTCOME_HEAD), _para(outcome["text"])]
    if outcome["learn"]:
        content += [Spacer(1, 4), _para("Background: " + outcome["learn"])]
    if outcome["causes"]:
        content += [Spacer(1, 6), _para("Possible causes (not confirmed)", _LABEL)] + _bullets(outcome["causes"])
    if outcome["hardware"]:
        content += [Spacer(1, 4), _para(HARDWARE_NOTE, _SMALL)]
    box = Table([[content]], colWidths=[CONTENT_WIDTH])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("LINEBEFORE", (0, 0), (0, -1), 4, OUTCOME_COLORS[outcome["kind"]]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return box


def _footer(reference):
    label = _plain(f"FixWise AI report {reference}")

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(PAGE_MARGIN, 10 * mm, label)
        canvas.drawRightString(A4[0] - PAGE_MARGIN, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def build_pdf(report):
    """Render the report as a PDF and return its bytes.

    The conclusion comes first and the (possibly long) list of steps last, so the part a
    technician needs most is always on page one.
    """
    story = [
        _para("FixWise AI", _BRAND),
        _para("Troubleshooting Report", _TITLE),
        HRFlowable(width="100%", thickness=2, color=INK, spaceAfter=8),
        _meta_table(report),
        _para("Problem described by the user", _HEADING),
        _para(report["problem"]),
        _para("Outcome", _HEADING),
        _outcome_box(report["outcome"]),
    ]

    analysis = report["analysis"]
    if analysis:
        title = "What FixWise AI understood" + (" (AI-generated, not verified)" if analysis["ai"] else "")
        story.append(_para(title, _HEADING))
        if analysis["summary"]:
            story.append(_para(analysis["summary"]))
        if analysis["symptoms"]:
            story += [Spacer(1, 4), _para("Symptoms", _LABEL)] + _bullets(analysis["symptoms"])
        if analysis["possible_causes"]:
            story += [Spacer(1, 4), _para("Possible causes (not confirmed)", _LABEL)] + _bullets(analysis["possible_causes"])

    story.append(_para("Questions and steps", _HEADING))
    if report["steps"]:
        story.append(_steps_table(report["steps"]))
    else:
        story.append(_para("None. The request was referred before any step was tried."))

    story += [Spacer(1, 12), _para("Note: " + report["disclaimer"], _SMALL)]

    buffer = BytesIO()
    footer = _footer(report["reference"])
    SimpleDocTemplate(
        buffer, pagesize=A4, title=TITLE, author="FixWise AI",
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN, topMargin=PAGE_MARGIN, bottomMargin=20 * mm,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
