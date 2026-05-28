"""Моніторинг рослин — API та сховище."""

import json
from unittest.mock import MagicMock, patch

import pytest

from monitoring.models import new_finding
from monitoring.store import append_finding, clear_findings, load_findings, query_findings
from web.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    findings = tmp_path / "findings.json"
    monkeypatch.setattr(
        "monitoring.config_loader.findings_path",
        lambda: findings,
    )
    from monitoring.service import reset_monitoring_service

    reset_monitoring_service()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    reset_monitoring_service()
    clear_findings()


def test_store_append_and_query(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "monitoring.config_loader.findings_path",
        lambda: tmp_path / "f.json",
    )
    clear_findings()
    rec = append_finding(
        new_finding(
            crop="vineyard",
            vehicle_id="rover_1",
            lat=50.45,
            lon=30.52,
            issue_type="disease",
            label="downy_mildew_suspect",
            confidence=0.6,
            severity="low",
        )
    )
    assert rec["id"]
    items = query_findings(vehicle_id="rover_1", crop="vineyard")
    assert len(items) == 1
    assert items[0]["label"] == "downy_mildew_suspect"


def test_monitoring_config_api(client):
    r = client.get("/api/monitoring/config")
    assert r.status_code == 200
    data = r.get_json()
    assert data["enabled"] is True
    assert any(c["id"] == "vineyard" for c in data["crops"])


def test_monitoring_crop_and_sample(client, mock_controller):
    from simulator.fleet_registry import register_vehicle, unregister_all
    from simulator.sim_stub import SimStub

    unregister_all()
    register_vehicle("rover_1", SimStub(50.45, 30.52))
    r = client.put(
        "/api/monitoring/crop",
        data=json.dumps({"crop": "banana"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.get_json()["crop"] == "banana"

    with patch("monitoring.analyzer.analyze_point") as ap:
        from monitoring.remote_client import RemoteAnalysisResult

        ap.return_value = RemoteAnalysisResult(
            detections=[],
            model_status="mock_server",
            message="ok",
            remote_ok=True,
        )
        r2 = client.post(
            "/api/monitoring/sample",
            data=json.dumps({"vehicle_id": "rover_1"}),
            content_type="application/json",
        )
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["crop"] == "banana"


def test_survey_blocks_when_mission_active(client, mock_controller):
    from web.fleet import get_fleet

    v = get_fleet().selected
    v.mission_waypoints = [
        {"lat": 50.45, "lon": 30.52},
        {"lat": 50.451, "lon": 30.525},
    ]
    v.control_mode = "autonomous"
    with patch.object(v.mission_runner, "phase", "running"):
        r = client.post(
            "/api/monitoring/survey/start",
            data=json.dumps({"vehicle_id": v.id}),
            content_type="application/json",
        )
    assert r.status_code == 409
