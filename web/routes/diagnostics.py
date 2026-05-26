"""Health check and session log download."""

from flask import Blueprint, Response, jsonify

from web.diagnostics import build_health, build_session_log_text
from web.session_log import record

diagnostics_bp = Blueprint("diagnostics", __name__)


@diagnostics_bp.route("/api/health", methods=["GET"])
def api_health():
    return jsonify(build_health())


@diagnostics_bp.route("/api/diagnostics/session-log", methods=["GET"])
def api_session_log():
    record("session_log_download")
    body = build_session_log_text()
    stamp = __import__("time").strftime("%Y%m%d_%H%M%S")
    return Response(
        body,
        mimetype="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="gcs_session_{stamp}.log"',
        },
    )
