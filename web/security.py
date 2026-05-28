"""HTTPS-налаштування та Bearer-захист API GCS."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from flask import Request, jsonify


def _system_cfg() -> dict:
    from config.config_paths import system_config_path
    import yaml

    with open(system_config_path(), "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def security_config() -> Dict[str, Any]:
    web = _system_cfg().get("web") or {}
    sec = dict(web.get("security") or {})
    env_key = os.environ.get("GCS_API_KEY", "").strip()
    if env_key:
        sec["api_key"] = env_key
    return sec


def tls_config() -> Dict[str, Any]:
    web = _system_cfg().get("web") or {}
    return dict(web.get("tls") or {})


def api_key_configured() -> str:
    return str(security_config().get("api_key") or "").strip()


def _allow_localhost_without_auth() -> bool:
    return bool(security_config().get("allow_localhost_without_auth", True))


def _is_local_request(req: Request) -> bool:
    addr = (req.remote_addr or "").strip()
    return addr in ("127.0.0.1", "::1", "localhost") or addr.startswith("127.")


def _public_path(path: str) -> bool:
    if path in ("/", "/gcs", "/favicon.ico"):
        return True
    if path.startswith("/static/"):
        return True
    return False


def _rpi_upload_authorized(req: Request) -> bool:
    if req.path != "/api/monitoring/upload":
        return False
    try:
        from monitoring.rpi_uplink import upload_token_expected

        expected = upload_token_expected()
        if not expected:
            return False
        got = (
            req.headers.get("X-Upload-Token")
            or (req.form.get("token") if req.form else "")
            or ""
        ).strip()
        return got == expected
    except Exception:
        return False


def check_api_auth(req: Request) -> Optional[Tuple[dict, int]]:
    """None = OK; інакше (payload, status)."""
    if not req.path.startswith("/api/"):
        return None
    if req.path in ("/api/security/status",):
        return None
    if _rpi_upload_authorized(req):
        return None

    key = api_key_configured()
    if not key:
        return None

    if _allow_localhost_without_auth() and _is_local_request(req):
        return None

    auth = (req.headers.get("Authorization") or "").strip()
    if auth == f"Bearer {key}":
        return None
    alt = (req.headers.get("X-Api-Key") or "").strip()
    if alt == key:
        return None

    return {
        "error": "unauthorized",
        "message": "Потрібен заголовок Authorization: Bearer <api_key>",
    }, 401


def register_security(app) -> None:
    @app.before_request
    def _gcs_api_auth():
        from flask import request

        result = check_api_auth(request)
        if result:
            return jsonify(result[0]), result[1]
        return None

    @app.route("/api/security/status", methods=["GET"])
    def api_security_status():
        tls = tls_config()
        return jsonify({
            "api_key_required": bool(api_key_configured()),
            "allow_localhost_without_auth": _allow_localhost_without_auth(),
            "tls_enabled": bool(tls.get("enabled")),
        })


def ssl_context():
    """Кортеж (cert, key) для app.run(ssl_context=...) або None."""
    tls = tls_config()
    if not tls.get("enabled"):
        return None
    cert = str(tls.get("cert_file") or "").strip()
    key = str(tls.get("key_file") or "").strip()
    if not cert or not key:
        return None
    from pathlib import Path
    from config.config_paths import project_root

    root = project_root()
    cp = Path(cert) if Path(cert).is_absolute() else root / cert
    kp = Path(key) if Path(key).is_absolute() else root / key
    if not cp.is_file() or not kp.is_file():
        return None
    return (str(cp), str(kp))
