"""E2E: Flask POST /api/monitoring/sample з remote.mode=remote + in-process server."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from simulator.fleet_registry import register_vehicle, unregister_all
from simulator.sim_stub import SimStub
from tests.helpers_monitoring import write_remote_monitoring_cfg
from web.server import app


@pytest.fixture
def client(tmp_path, monkeypatch, analysis_server):
    findings = tmp_path / "findings.json"
    cfg_path = tmp_path / "monitoring.remote.json"
    write_remote_monitoring_cfg(
        cfg_path,
        base_url=analysis_server["base_url"],
        queue_dir=tmp_path / "outbox",
        captures_dir=tmp_path / "caps",
        findings_file=findings,
    )
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    monkeypatch.setenv("MONITORING_CONFIG", str(cfg_path))
    monkeypatch.setattr(
        "monitoring.config_loader.findings_path",
        lambda: findings,
    )
    from monitoring import config_loader
    from monitoring.service import reset_monitoring_service
    import web.fleet as fm

    fm._fleet = None
    config_loader._CACHE = None
    reset_monitoring_service()

    unregister_all()
    register_vehicle("rover_1", SimStub(50.45, 30.52))

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    reset_monitoring_service()
    config_loader._CACHE = None
    fm._fleet = None
    unregister_all()


def test_monitoring_sample_e2e_remote(client):
    from web.fleet import get_fleet

    v = get_fleet().get_vehicle("rover_1")
    ctrl = MagicMock()
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": True,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch.object(v, "get_controller", return_value=ctrl):
        with patch("web.preflight._sim_active", return_value=True):
            with patch("web.geofence.is_enabled", return_value=False):
                r = client.post(
                    "/api/monitoring/sample",
                    data=json.dumps({"vehicle_id": "rover_1", "crop": "vineyard"}),
                    content_type="application/json",
                )
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("remote_ok") is True
    assert body.get("crop") == "vineyard"

    r2 = client.get("/api/monitoring/findings?vehicle_id=rover_1")
    assert r2.status_code == 200


def test_monitoring_sample_preflight_409_when_disarmed(client):
    from web.fleet import get_fleet

    v = get_fleet().get_vehicle("rover_1")
    ctrl = MagicMock()
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": False,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch.object(v, "get_controller", return_value=ctrl):
        with patch("web.preflight._sim_active", return_value=False):
            with patch("web.geofence.is_enabled", return_value=False):
                r = client.post(
                    "/api/monitoring/sample",
                    data=json.dumps({"vehicle_id": "rover_1"}),
                    content_type="application/json",
                )
    assert r.status_code == 409
    assert r.get_json().get("error") == "preflight_failed"
