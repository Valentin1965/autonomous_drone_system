"""snap_to не чіпає дрон під час місії (паралельний флот)."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from simulator.fleet_registry import (
    get_position,
    register_vehicle,
    snap_to,
    snap_to_start_waypoint_if_needed,
    unregister_all,
)
from simulator.sim_stub import SimStub
from web.fleet import get_fleet
from web.server import app


@pytest.fixture(autouse=True)
def reset_fleet():
    unregister_all()
    import web.fleet as fm

    fm._fleet = None
    yield
    unregister_all()
    fm._fleet = None


def _make_ctrl(stub, vid):
    ctrl = MagicMock()
    ctrl.goto_latlon = MagicMock()
    ctrl.arm = MagicMock()
    ctrl.stop = MagicMock()
    ctrl.ensure_connected = MagicMock()
    ctrl.get_status.side_effect = lambda: {
        "connected": True,
        "armed": True,
        "gps": stub.get_position(),
    }
    return ctrl


def test_snap_to_ignored_during_running_mission():
    stub = SimStub(50.4501, 30.5234)
    register_vehicle("rover_1", stub)
    fleet = get_fleet()
    v = fleet.get_vehicle("rover_1")
    v.control_mode = "autonomous"
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4510, "lon": 30.5240},
    ]
    v.mission_waypoints = list(wps)

    with patch.object(v, "get_controller", return_value=_make_ctrl(stub, "rover_1")):
        with patch("web.preflight._sim_active", return_value=True):
            with patch("web.geofence.is_enabled", return_value=False):
                app.config["TESTING"] = True
                client = app.test_client()
                r = client.post(
                    "/api/fleet/mission/run",
                    data=json.dumps({
                        "vehicle_id": "rover_1",
                        "waypoints": wps,
                        "speed": 1.0,
                    }),
                    content_type="application/json",
                )
                assert r.status_code == 200
                time.sleep(0.15)
                pos_before = dict(get_position("rover_1"))
                snap_to(50.4600, 30.5300, "rover_1")
                pos_after = dict(get_position("rover_1"))
                assert pos_before["lat"] == pos_after["lat"]
                assert pos_before["lon"] == pos_after["lon"]


def test_snap_to_start_blocked_during_mission():
    stub = SimStub(50.4501, 30.5234)
    register_vehicle("rover_1", stub)
    fleet = get_fleet()
    v = fleet.get_vehicle("rover_1")
    v.control_mode = "autonomous"
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4520, "lon": 30.5250},
    ]
    v.mission_waypoints = list(wps)
    v.mission_runner.start(wps, speed_m_s=1.0)
    time.sleep(0.05)
    stub.lat = 50.4515
    stub.lon = 30.5245
    ok = snap_to_start_waypoint_if_needed(wps, "rover_1")
    assert ok is False
    assert abs(stub.lat - 50.4515) < 1e-6
