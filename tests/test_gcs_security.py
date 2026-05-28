"""GCS API Bearer та /api/security/status."""

import json

import pytest

from web.server import app


@pytest.fixture
def sec_client(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "SYSTEM_CONFIG",
        str(tmp_path / "sys.yaml"),
    )
    cfg = tmp_path / "sys.yaml"
    cfg.write_text(
        """
web:
  host: 127.0.0.1
  port: 8080
  security:
    api_key: test-secret
    allow_localhost_without_auth: false
""",
        encoding="utf-8",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_requires_bearer(sec_client):
    r = sec_client.get("/api/status")
    assert r.status_code == 401

    r2 = sec_client.get(
        "/api/status",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert r2.status_code == 200


def test_security_status(sec_client):
    r = sec_client.get("/api/security/status")
    assert r.status_code == 200
    assert r.get_json().get("api_key_required") is True


def test_localhost_bypass(client, monkeypatch, tmp_path):
    """Dev profile: localhost without Bearer."""
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    from web import security

    monkeypatch.setattr(
        security,
        "security_config",
        lambda: {"api_key": "x", "allow_localhost_without_auth": True},
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.get("/api/security/status")
    assert r.status_code == 200
