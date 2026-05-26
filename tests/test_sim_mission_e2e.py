"""E2E: місія на SimStub через Flask API (без UDP)."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from simulator.registry import register, unregister, set_guided_target
from simulator.sim_stub import SimStub
from web.server import app
from web.state import drone_state


@pytest.fixture
def sim_client():
    stub = SimStub()
    register(stub)
    app.config["TESTING"] = True
    ctrl = MagicMock()
    ctrl.frame = "body"
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": True,
        "gps": stub.get_position(),
    }

    def _goto(lat, lon, speed_m_s=1.0):
        set_guided_target(lat, lon, speed_m_s)

    ctrl.goto_latlon.side_effect = _goto
    ctrl.arm = MagicMock()
    ctrl.stop = MagicMock()
    ctrl.ensure_connected = MagicMock()

    with patch("web.state.drone_state.get_controller", return_value=ctrl):
        with app.test_client() as client:
            drone_state.mission_waypoints = []
            drone_state.set_control_mode("autonomous")
            yield client, stub, ctrl
    unregister()


def test_sim_load_demo(sim_client):
    client, _, _ = sim_client
    r = client.post("/api/sim/load_demo")
    assert r.status_code == 200
    assert r.get_json()["count"] >= 3
    assert len(drone_state.mission_waypoints) >= 3


def test_mission_run_to_at_last(sim_client):
    client, stub, ctrl = sim_client
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4508, "lon": 30.5240},
        {"lat": 50.4515, "lon": 30.5246},
    ]
    drone_state.mission_waypoints = list(wps)
    r = client.post(
        "/api/mission/run",
        data=json.dumps({"speed": 1.0}),
        content_type="application/json",
    )
    assert r.status_code == 200

    deadline = time.time() + 8.0
    phase = "running"
    while time.time() < deadline:
        st = client.get("/api/mission/status").get_json()
        phase = st.get("phase", phase)
        if phase in ("at_last", "completed", "aborted"):
            break
        time.sleep(0.15)

    assert phase == "at_last", f"expected at_last, got {phase}"
    ctrl.stop.assert_called()


def test_sim_api_requires_sim():
    unregister()
    app.config["TESTING"] = True
    with app.test_client() as client:
        r = client.post("/api/sim/load_demo")
    assert r.status_code == 503
