"""Місія чекає, поки hazard_blocks_motion активний."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from simulator.fleet_registry import register_vehicle, set_guided_target, unregister_all
from simulator.sim_stub import SimStub
from web.fleet import get_fleet
from web.server import app


@pytest.fixture
def sim_mission_client():
    stub = SimStub(50.4501, 30.5234)
    register_vehicle("rover_1", stub)
    app.config["TESTING"] = True
    fleet = get_fleet()
    v = fleet.get_vehicle("rover_1")
    v.control_mode = "autonomous"
    ctrl = MagicMock()

    def _goto(lat, lon, speed_m_s=1.0):
        set_guided_target(lat, lon, speed_m_s, "rover_1")

    ctrl.goto_latlon.side_effect = _goto
    ctrl.arm = MagicMock()
    ctrl.stop = MagicMock()
    ctrl.ensure_connected = MagicMock()
    ctrl.get_status.side_effect = lambda: {
        "connected": True,
        "armed": True,
        "gps": stub.get_position(),
    }

    patches = [
        patch.object(v, "get_controller", return_value=ctrl),
        patch("web.preflight._sim_active", return_value=True),
        patch("web.geofence.is_enabled", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        with app.test_client() as client:
            yield client, stub, v, ctrl
    finally:
        for p in patches:
            p.stop()
    unregister_all()


def test_mission_waits_while_hazard_active(sim_mission_client):
    client, stub, v, ctrl = sim_mission_client
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4520, "lon": 30.5250},
        {"lat": 50.4535, "lon": 30.5265},
    ]
    v.mission_waypoints = list(wps)
    r = client.post(
        "/api/mission/run",
        data=json.dumps({"speed": 1.0, "waypoints": wps}),
        content_type="application/json",
    )
    assert r.status_code == 200

    with patch("web.tracker_service.hazard_blocks_motion", return_value=True):
        time.sleep(0.8)
        st = client.get("/api/mission/status").get_json()
        assert st.get("phase") == "running"
        assert ctrl.stop.call_count >= 1

    with patch("web.tracker_service.hazard_blocks_motion", return_value=False):
        deadline = time.time() + 12.0
        phase = "running"
        while time.time() < deadline:
            st = client.get("/api/mission/status").get_json()
            phase = st.get("phase", phase)
            if phase in ("at_last", "completed", "aborted"):
                break
            time.sleep(0.12)
        assert phase == "at_last"
