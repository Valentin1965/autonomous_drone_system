"""Зупинка на останній точці маршруту (не дрейф до геозони)."""

import json
import time

import pytest

from simulator.fleet_registry import register_vehicle, set_guided_target, unregister_all
from simulator.sim_stub import SimStub
from web.server import app


@pytest.fixture
def sim_mission_client():
    stub = SimStub(50.4501, 30.5234)
    register_vehicle("rover_1", stub)
    app.config["TESTING"] = True
    from unittest.mock import MagicMock, patch

    from web.fleet import get_fleet

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

    with patch.object(v, "get_controller", return_value=ctrl):
        with patch("web.preflight._sim_active", return_value=True):
            with patch("web.geofence.is_enabled", return_value=False):
                with app.test_client() as client:
                    yield client, stub, v
    unregister_all()


def test_mission_stops_at_last_waypoint(sim_mission_client):
    client, stub, v = sim_mission_client
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4508, "lon": 30.5240},
        {"lat": 50.4515, "lon": 30.5246},
    ]
    v.mission_waypoints = list(wps)
    r = client.post(
        "/api/fleet/mission/run",
        data=json.dumps({"vehicle_id": "rover_1", "waypoints": wps, "speed": 1.2}),
        content_type="application/json",
    )
    assert r.status_code == 200

    deadline = time.time() + 12.0
    phase = "running"
    while time.time() < deadline:
        st = client.get("/api/mission/status?vehicle_id=rover_1").get_json()
        phase = st.get("phase", phase)
        if phase in ("at_last", "completed", "aborted"):
            break
        time.sleep(0.12)

    assert phase == "at_last", f"expected at_last, got {phase}"
    pos = stub.get_position()
    dist_end = (
        (float(pos["lat"]) - wps[-1]["lat"]) ** 2
        + (float(pos["lon"]) - wps[-1]["lon"]) ** 2
    ) ** 0.5
    assert dist_end < 0.00015, "rover should stay at last waypoint"
    with stub.lock:
        assert stub.target_lat is None
        assert stub.target_speed < 0.1
