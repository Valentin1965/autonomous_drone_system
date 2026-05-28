"""Priority 1: health, mission import/export, config paths."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

def test_health_endpoint(client, mock_controller):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "version" in data
    assert "mavlink_profile" in data


def test_session_log_download(client, mock_controller):
    r = client.get("/api/diagnostics/session-log")
    assert r.status_code == 200
    assert b"GCS session log" in r.data
    assert "attachment" in r.headers.get("Content-Disposition", "")


def test_mission_export_import(client, mock_controller):
    from web.state import drone_state

    drone_state.mission_waypoints = []
    r = client.get("/api/mission/export")
    assert r.status_code == 200
    assert r.get_json()["format"] == "gcs_mission_v2"

    payload = {
        "format": "gcs_mission_v2",
        "waypoints": [
            {"lat": 50.451, "lon": 30.524},
            {"lat": 50.452, "lon": 30.525},
        ],
    }
    r = client.post(
        "/api/mission/import",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.get_json()["count"] == 2
    assert len(drone_state.mission_waypoints) == 2


def test_status_includes_warnings(client, mock_controller):
    from simulator.sim_stub import SimStub

    stub = SimStub(50.45, 30.52)
    with patch("simulator.fleet_registry.get_sim", return_value=stub):
        with patch("mavlink.runtime_config.mavlink_profile", return_value="px4"):
            r = client.get("/api/status")
    assert r.status_code == 200
    data = r.get_json()
    assert "warnings" in data
    assert any("симулятор" in w.lower() for w in data["warnings"])


def test_variant2_config_files_load():
    root = Path(__file__).resolve().parent.parent
    for name in ("system_gcs.yaml", "system_rpi.yaml"):
        path = root / "config" / name
        assert path.is_file(), name
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert cfg.get("deployment") == "variant_2"
        assert "mavlink" in cfg
