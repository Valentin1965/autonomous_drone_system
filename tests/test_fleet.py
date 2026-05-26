"""Fleet manager and multi-vehicle mission."""

import json
from unittest.mock import MagicMock, patch

import pytest

from simulator.fleet_registry import register_vehicle, unregister_all
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


def test_fleet_loads_two_vehicles(monkeypatch):
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    fleet = get_fleet()
    fleet.load_config()
    assert len(fleet.vehicles) >= 2
    assert fleet.multi


def test_fleet_select(client=None):
    app.config["TESTING"] = True
    stub1 = SimStub(50.45, 30.52)
    stub2 = SimStub(50.46, 30.53)
    register_vehicle("rover_1", stub1)
    register_vehicle("rover_2", stub2)
    with patch("web.state.drone_state.get_controller") as gc:
        gc.return_value = MagicMock(get_status=lambda: {"connected": True, "gps": {}})
        with app.test_client() as client:
            r = client.post(
                "/api/fleet/select",
                data=json.dumps({"vehicle_id": "rover_2"}),
                content_type="application/json",
            )
    assert r.status_code == 200
    assert r.get_json()["selected_vehicle_id"] == "rover_2"


def test_fleet_mission_run_endpoint(client, mock_controller):
    from simulator.fleet_registry import register_vehicle, unregister_all
    from simulator.sim_stub import SimStub

    unregister_all()
    register_vehicle("rover_1", SimStub(50.45, 30.52))
    register_vehicle("rover_2", SimStub(50.46, 30.53))
    import web.fleet as fm

    fm._fleet = None
    fleet = get_fleet()
    v2 = fleet.get_vehicle("rover_2")
    v2.control_mode = "autonomous"
    v2.mission_waypoints = [
        {"lat": 50.451, "lon": 30.524},
        {"lat": 50.452, "lon": 30.525},
    ]
    with patch.object(v2, "get_controller") as gc:
        gc.return_value = MagicMock(
            get_status=lambda: {"connected": True, "gps": {}},
            ensure_connected=lambda: None,
            arm=lambda: None,
        )
        r = client.post(
            "/api/fleet/mission/run",
            data=json.dumps({"vehicle_id": "rover_2", "speed": 1.0}),
            content_type="application/json",
        )
    assert r.status_code == 200
    assert r.get_json()["vehicle_id"] == "rover_2"
