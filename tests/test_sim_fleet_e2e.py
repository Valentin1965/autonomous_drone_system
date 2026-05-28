"""E2E sim: два rover паралельно завершують маршрут (at_last)."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from simulator.fleet_registry import register_vehicle, set_guided_target, unregister_all
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

    def _goto(lat, lon, speed_m_s=1.0):
        set_guided_target(lat, lon, speed_m_s, vid)

    ctrl.goto_latlon.side_effect = _goto
    ctrl.arm = MagicMock()
    ctrl.stop = MagicMock()
    ctrl.ensure_connected = MagicMock()
    ctrl.get_status.side_effect = lambda: {
        "connected": True,
        "armed": True,
        "gps": stub.get_position(),
    }
    return ctrl


@pytest.fixture
def fleet_client(monkeypatch):
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    stub1 = SimStub(50.4501, 30.5234)
    stub2 = SimStub(50.4508, 30.5240)
    register_vehicle("rover_1", stub1)
    register_vehicle("rover_2", stub2)
    fleet = get_fleet()
    v1 = fleet.get_vehicle("rover_1")
    v2 = fleet.get_vehicle("rover_2")
    v1.control_mode = "autonomous"
    v2.control_mode = "autonomous"
    wps1 = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4506, "lon": 30.5240},
        {"lat": 50.4511, "lon": 30.5246},
    ]
    wps2 = [
        {"lat": 50.4508, "lon": 30.5240},
        {"lat": 50.4513, "lon": 30.5246},
        {"lat": 50.4518, "lon": 30.5252},
    ]
    v1.mission_waypoints = list(wps1)
    v2.mission_waypoints = list(wps2)

    patches = [
        patch.object(v1, "get_controller", return_value=_make_ctrl(stub1, "rover_1")),
        patch.object(v2, "get_controller", return_value=_make_ctrl(stub2, "rover_2")),
        patch("web.preflight._sim_active", return_value=True),
        patch("web.geofence.is_enabled", return_value=False),
    ]
    for p in patches:
        p.start()
    app.config["TESTING"] = True
    try:
        with app.test_client() as client:
            yield client, v1, v2, wps1, wps2
    finally:
        for p in patches:
            p.stop()


def _wait_phase(client, vid, timeout_s=14.0):
    deadline = time.time() + timeout_s
    phase = "running"
    while time.time() < deadline:
        st = client.get(f"/api/mission/status?vehicle_id={vid}").get_json()
        phase = st.get("phase", phase)
        if phase in ("at_last", "completed", "aborted"):
            return phase
        time.sleep(0.12)
    return phase


def test_sync_start_blocked_while_mission_running(fleet_client):
    client, v1, _v2, wps1, _wps2 = fleet_client
    r = client.post(
        "/api/fleet/mission/run",
        data=json.dumps({
            "vehicle_id": "rover_1",
            "waypoints": wps1,
            "speed": 1.2,
        }),
        content_type="application/json",
    )
    assert r.status_code == 200
    time.sleep(0.25)
    sync = client.post(
        "/api/mission/sync_start?vehicle_id=rover_1",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert sync.status_code == 409
    assert sync.get_json().get("reason") == "mission_active"


def test_fleet_two_vehicles_reach_at_last(fleet_client):
    client, v1, v2, wps1, wps2 = fleet_client
    r1 = client.post(
        "/api/fleet/mission/run",
        data=json.dumps({
            "vehicle_id": "rover_1",
            "waypoints": wps1,
            "speed": 1.2,
        }),
        content_type="application/json",
    )
    r2 = client.post(
        "/api/fleet/mission/run",
        data=json.dumps({
            "vehicle_id": "rover_2",
            "waypoints": wps2,
            "speed": 1.2,
        }),
        content_type="application/json",
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    time.sleep(0.3)
    st1 = client.get("/api/mission/status?vehicle_id=rover_1").get_json()
    st2 = client.get("/api/mission/status?vehicle_id=rover_2").get_json()
    assert st1.get("phase") == "running"
    assert st2.get("phase") == "running"

    p1 = _wait_phase(client, "rover_1")
    p2 = _wait_phase(client, "rover_2")
    assert p1 == "at_last", f"rover_1 phase={p1}"
    assert p2 == "at_last", f"rover_2 phase={p2}"
