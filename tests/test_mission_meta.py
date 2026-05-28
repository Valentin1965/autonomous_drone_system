"""Mission JSON v2 metadata and fleet configure."""

import json
from pathlib import Path

import pytest
import yaml

from web.fleet import get_fleet, reset_fleet_singleton
from web.mission_record import (
    MISSION_FORMAT_V2,
    export_payload,
    record_from_import,
)
from web.server import app


@pytest.fixture(autouse=True)
def reset_fleet():
    import web.fleet as fm

    fm._fleet = None
    yield
    fm._fleet = None


def test_mission_record_export_import(client, mock_controller):
    payload = export_payload(
        "rover_1",
        [{"lat": 50.45, "lon": 30.52}],
        {
            "work_started_at": "2026-05-26T09:00:00",
            "work_finished_at": None,
            "spraying": {"applied": True, "product": "Test herbicide"},
            "field_notes": "Field A",
        },
        1.0,
    )
    assert payload["format"] == MISSION_FORMAT_V2
    assert payload["spraying"]["applied"] is True
    assert payload["field_notes"] == "Field A"

    r = client.get("/api/mission/export")
    assert r.status_code == 200
    assert r.get_json()["format"] == MISSION_FORMAT_V2

    imp = {
        "format": "gcs_mission_v1",
        "waypoints": [{"lat": 50.451, "lon": 30.524}],
        "work": {"started_at": "2026-05-26T10:00:00"},
        "spraying": {"applied": True, "product": "X"},
        "field_notes": "note",
    }
    r = client.post(
        "/api/mission/import",
        data=json.dumps(imp),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] == 1
    assert data["record"]["spraying"]["applied"] is True
    assert data["record"]["field_notes"] == "note"


def test_mission_record_put(client, mock_controller):
    body = {
        "record": {
            "work_started_at": "2026-05-26T08:30:00",
            "spraying": {"applied": False, "product": ""},
            "field_notes": "коментар",
        }
    }
    r = client.put(
        "/api/mission/record",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.get_json()["record"]["field_notes"] == "коментар"


def test_fleet_configure_count(tmp_path, monkeypatch):
    runtime = tmp_path / "fleet_runtime.yaml"
    monkeypatch.setattr("web.fleet_config.RUNTIME_PATH", runtime)
    reset_fleet_singleton()
    fleet = get_fleet()
    fleet.load_config()
    before = len(fleet.vehicles)
    result = fleet.configure_fleet_count(3)
    assert result["count"] == 3
    assert len(fleet.vehicles) == 3
    assert runtime.is_file()
    saved = yaml.safe_load(runtime.read_text(encoding="utf-8"))
    assert len(saved["vehicles"]) == 3
    fleet.configure_fleet_count(before)


def test_fleet_configure_api(client, mock_controller, tmp_path, monkeypatch):
    from unittest.mock import patch

    from web.fleet import get_fleet

    runtime = tmp_path / "fleet_runtime.yaml"
    monkeypatch.setattr("web.fleet_config.RUNTIME_PATH", runtime)
    reset_fleet_singleton()
    fleet = get_fleet()
    with patch.object(fleet, "_sync_simulators_for_fleet", return_value=False):
        with patch.object(fleet, "warmup_connections", return_value={"rover_1": "ok"}):
            r = client.post(
                "/api/fleet/configure",
                data=json.dumps({"count": 2}),
                content_type="application/json",
            )
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] == 2
    assert data.get("requires_restart") is True


def test_record_from_import_v2():
    rec = record_from_import({
        "work": {"started_at": "2026-01-01T12:00:00", "finished_at": "2026-01-01T14:00:00"},
        "spraying": {"applied": True, "product": "P"},
        "field_notes": "N",
    })
    assert rec["work_started_at"] == "2026-01-01T12:00:00"
    assert rec["spraying"]["product"] == "P"
