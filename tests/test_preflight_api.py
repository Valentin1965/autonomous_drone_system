"""GET /api/preflight — per-vehicle preflight для флоту."""

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


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_preflight_api_sim_ready(client, monkeypatch):
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    stub = SimStub(50.45, 30.52)
    register_vehicle("rover_1", stub)
    fleet = get_fleet()
    v = fleet.get_vehicle("rover_1")
    v.mission_waypoints = [
        {"lat": 50.45, "lon": 30.52},
        {"lat": 50.451, "lon": 30.525},
    ]

    ctrl = MagicMock()
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": False,
        "reconnecting": False,
        "gps": stub.get_position(),
    }

    with patch.object(v, "get_controller", return_value=ctrl):
        with patch("web.preflight._sim_active", return_value=True):
            with patch("web.geofence.is_enabled", return_value=False):
                r = client.get(
                    "/api/preflight?vehicle_id=rover_1&require_route=1"
                )
    assert r.status_code == 200
    data = r.get_json()
    assert data["vehicle_id"] == "rover_1"
    assert data["ready_for_mission"] is True


def test_preflight_api_blocks_without_route(client, monkeypatch):
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    stub = SimStub(50.45, 30.52)
    register_vehicle("rover_1", stub)
    v = get_fleet().get_vehicle("rover_1")
    v.mission_waypoints = []
    ctrl = MagicMock()
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": True,
        "reconnecting": False,
        "gps": stub.get_position(),
    }
    with patch.object(v, "get_controller", return_value=ctrl):
        with patch("web.preflight._sim_active", return_value=True):
            with patch("web.geofence.is_enabled", return_value=False):
                r = client.get(
                    "/api/preflight?vehicle_id=rover_1&require_route=1"
                )
    assert r.status_code == 200
    assert r.get_json()["ready_for_mission"] is False
