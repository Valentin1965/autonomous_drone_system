"""E2E: місія на SimStub через Flask API (без UDP)."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from simulator.fleet_registry import register_vehicle, set_guided_target, unregister_all
from simulator.sim_stub import SimStub
from web.server import app


@pytest.fixture
def sim_client():
    unregister_all()
    import web.fleet as fm

    fm._fleet = None
    stub = SimStub(50.4501, 30.5234)
    register_vehicle("rover_1", stub)
    from simulator.registry import register

    register(stub)
    app.config["TESTING"] = True
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

    patches = [
        patch.object(v, "get_controller", return_value=ctrl),
        patch("web.preflight._sim_active", return_value=True),
        patch("web.geofence.is_enabled", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        with app.test_client() as client:
            yield client, stub, ctrl
    finally:
        for p in patches:
            p.stop()
    unregister_all()
    fm._fleet = None


def test_sim_load_demo(sim_client):
    client, _, _ = sim_client
    r = client.post("/api/sim/load_demo")
    assert r.status_code == 200
    assert r.get_json()["count"] >= 3
    from web.fleet import get_fleet

    assert len(get_fleet().selected.mission_waypoints) >= 3


def test_mission_passes_second_waypoint_with_four_points(sim_client):
    """Після 2-ї точки (index 1) місія йде далі, а не зависає."""
    client, stub, _ctrl = sim_client
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4508, "lon": 30.5240},
        {"lat": 50.4515, "lon": 30.5246},
        {"lat": 50.4522, "lon": 30.5252},
    ]
    from web.fleet import get_fleet

    v = get_fleet().get_vehicle("rover_1")
    v.mission_waypoints = list(wps)
    r = client.post(
        "/api/mission/run",
        data=json.dumps({"speed": 1.2, "waypoints": wps}),
        content_type="application/json",
    )
    assert r.status_code == 200

    saw_idx_ge_2 = False
    deadline = time.time() + 14.0
    while time.time() < deadline:
        st = client.get("/api/mission/status?vehicle_id=rover_1").get_json()
        idx = int(st.get("index") or 0)
        if idx >= 2:
            saw_idx_ge_2 = True
        if st.get("phase") in ("at_last", "completed", "aborted"):
            break
        time.sleep(0.1)

    assert saw_idx_ge_2, "mission should advance past waypoint 2 (index >= 2)"


def test_mission_run_to_at_last(sim_client):
    client, stub, ctrl = sim_client
    wps = [
        {"lat": 50.4501, "lon": 30.5234},
        {"lat": 50.4508, "lon": 30.5240},
        {"lat": 50.4515, "lon": 30.5246},
    ]
    from web.fleet import get_fleet

    v = get_fleet().get_vehicle("rover_1")
    v.mission_waypoints = list(wps)
    r = client.post(
        "/api/mission/run",
        data=json.dumps({"speed": 1.0, "waypoints": wps}),
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
    ctrl.stop.assert_called()


def test_sim_api_requires_sim():
    unregister_all()
    import web.fleet as fm

    fm._fleet = None
    app.config["TESTING"] = True
    with app.test_client() as client:
        r = client.post("/api/sim/load_demo")
    assert r.status_code == 503
