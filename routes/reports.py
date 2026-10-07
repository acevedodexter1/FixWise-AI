"""Technician report: an on-screen page and a PDF download.

Two ways in:
  /troubleshoot/report[.pdf]               the interview in this browser (guests too)
  /dashboard/session/<id>/report[.pdf]     a saved session (its owner only)
"""
from io import BytesIO

from flask import Blueprint, abort, make_response, redirect, render_template, send_file, url_for
from flask_login import current_user, login_required

from extensions import db
from models import TroubleshootingSession
from routes.troubleshoot import _get_ts
from services import decision_tree_service as tree
from services import device_service, report_service
from services import troubleshooting_service as store

reports_bp = Blueprint("reports", __name__)


def _private(response):
    """Reports describe someone's computer problem, so browsers and proxies should not keep a copy."""
    response.headers["Cache-Control"] = "no-store"
    return response


def _current_report():
    ts = _get_ts()
    if not ts:
        return None
    return report_service.build_report(
        problem=ts["problem"],
        category=ts["category"],
        node=tree.get_node(ts["node"]),
        history=ts["history"],
        analysis=ts.get("analysis"),
        reference=report_service.reference_for(ts.get("db_id")),
        device=device_service.snapshot_for(ts.get("db_id")),
    )


def _saved_report(session_id):
    row = db.session.get(TroubleshootingSession, session_id)
    if row is None or row.user_id != current_user.id:
        abort(404)
    return report_service.build_report(
        problem=row.problem_description,
        category=row.category,
        node=tree.get_node(row.current_node),
        history=row.timeline(),
        status=row.status,
        analysis=store.load_analysis(row.id),
        reference=report_service.reference_for(row.id),
        started=row.created_at,
        device=device_service.snapshot_for(row.id),
    )


def _page(report, pdf_url, back_url, back_label):
    html = render_template(
        "troubleshoot/report.html",
        report=report,
        text=report_service.as_text(report),
        pdf_url=pdf_url,
        back_url=back_url,
        back_label=back_label,
    )
    return _private(make_response(html))


def _pdf(report):
    response = send_file(
        BytesIO(report_service.build_pdf(report)),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=report["filename"],
    )
    return _private(response)


@reports_bp.route("/troubleshoot/report")
def current_report():
    report = _current_report()
    if report is None:
        return redirect(url_for("home.home"))
    return _page(report, url_for("reports.current_pdf"), url_for("troubleshoot.interview"), "Back to result")


@reports_bp.route("/troubleshoot/report.pdf")
def current_pdf():
    report = _current_report()
    if report is None:
        return redirect(url_for("home.home"))
    return _pdf(report)


@reports_bp.route("/dashboard/session/<int:session_id>/report")
@login_required
def session_report(session_id):
    report = _saved_report(session_id)
    return _page(
        report,
        url_for("reports.session_pdf", session_id=session_id),
        url_for("history.detail", session_id=session_id),
        "Back to session",
    )


@reports_bp.route("/dashboard/session/<int:session_id>/report.pdf")
@login_required
def session_pdf(session_id):
    return _pdf(_saved_report(session_id))
