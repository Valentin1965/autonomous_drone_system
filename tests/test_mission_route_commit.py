"""Фіксація маршруту реальними GPS після першого ряду."""

import json
from unittest.mock import MagicMock, patch

import pytest

from web.mission_route import is_first_row_end_index
from web.mission_runner import MissionRunner
from web.server import app
from web.vehicle import Vehicle


def test_is_first_row_end_by_role():
    wps = [
        {"lat": 1.0, "lon": 2.0, "role": "row_start", "row_index": 0},
        {"lat": 1.1, "lon": 2.1, "role": "row_end", "row_index": 0},
        {"lat": 1.2, "lon": 2.2, "role": "row_start", "row_index": 1},
    ]
    assert is_first_row_end_index(1, wps) is True
    assert is_first_row_end_index(2, wps) is False


def test_commit_on_first_row_end():
    v = Vehicle("rover_1", "R1", "udp:127.0.0.1:14550")
    wps = [
        {"lat": 28.2916, "lon": -16.6291, "role": "row_start", "row_index": 0},
        {"lat": 28.2920, "lon": -16.6288, "role": "row_end", "row_index": 0},
    ]
    v.set_mission_draft(wps)
    runner = MissionRunner(v)
    runner._route_committed_this_run = False
    actual_gps = {"lat": 28.29155, "lon": -16.62905}
    runner._record_actual_at(0, actual_gps, wps)
    runner._record_actual_at(
        1,
        {"lat": 28.29201, "lon": -16.62879},
        wps,
    )
    assert v.mission_route_committed is True
    assert len(v.mission_waypoints) == 2
    assert v.mission_waypoints[0]["lat"] == pytest.approx(28.29155, abs=1e-5)
    assert v.mission_draft is None


def test_plan_draft_run_draft_only(client, mock_controller):
    from web.fleet import get_fleet

    get_fleet().selected.control_mode = "autonomous"

    plan = {
        "origin_lat": 28.2916,
        "origin_lon": -16.6291,
        "row_count": 2,
        "row_length_m": 20.0,
        "row_spacing_m": 1.0,
        "store_draft": True,
    }
    r = client.post(
        "/api/mission/plan-rows",
        data=json.dumps(plan),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert client.get("/api/mission").get_json()["waypoints"] == []

    run = {
        "speed": 1.0,
        "draft_only": True,
        "waypoints": [
            {"lat": 28.2916, "lon": -16.6291, "role": "row_start", "row_index": 0},
            {"lat": 28.2920, "lon": -16.6288, "role": "row_end", "row_index": 0},
        ],
    }
    with patch("web.mission_runner.MissionRunner.start") as mock_start, patch(
        "web.preflight.assert_ready_for_mission", return_value=None
    ), patch("web.geofence.is_enabled", return_value=False):
        mock_start.return_value = {"phase": "running", "active": True, "total": 2}
        r2 = client.post(
            "/api/mission/run",
            data=json.dumps(run),
            content_type="application/json",
        )
    assert r2.status_code == 200, r2.get_json()
    mock_start.assert_called_once()
    assert client.get("/api/mission").get_json()["waypoints"] == []
