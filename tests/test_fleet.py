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


def test_fleet_default_video_per_rover():
    from web.fleet_config import build_vehicle_entries, default_fleet_video_file

    assert default_fleet_video_file(0).endswith("vineyard_demo.mp4")
    assert default_fleet_video_file(4).endswith("vineyard_demo4.mp4")
    entries = build_vehicle_entries(5, {"mavlink": {"connection_sim": "udp:127.0.0.1:14550"}})
    assert len(entries) == 5
    assert entries[0]["video_file"].endswith("vineyard_demo.mp4")
    assert entries[4]["video_file"].endswith("vineyard_demo4.mp4")


def test_cv_config_for_vehicle_overrides_video():
    from web.tracker_service import cv_config_for_vehicle

    cfg = cv_config_for_vehicle("assets/videos/vineyard_demo2.mp4")
    assert cfg["video_file"] == "assets/videos/vineyard_demo2.mp4"
    assert cfg["source"] == "video"


def test_video_info_reports_directory(monkeypatch):
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    fleet = get_fleet()
    v = fleet.get_vehicle("rover_1")
    from web.tracker_service import video_info_for_vehicle

    info = video_info_for_vehicle(v)
    assert info["video_file"]
    assert info["video_dir_exists"] is True
    assert "videos_in_dir" in info
    assert "videos_count" in info


def test_fleet_cv_connect_api(client, mock_controller):
    with patch("web.tracker_service.connect_cv") as connect:
        connect.return_value = {
            "status": "started",
            "vehicle_id": "rover_1",
            "connected": True,
            "video_file": "assets/videos/vineyard_demo.mp4",
        }
        r = client.post(
            "/api/fleet/cv/connect",
            data=json.dumps({"vehicle_id": "rover_1"}),
            content_type="application/json",
        )
    assert r.status_code == 200
    assert r.get_json()["vehicle_id"] == "rover_1"


def test_fleet_payload_includes_cv_block(client, mock_controller):
    r = client.get("/api/fleet")
    assert r.status_code == 200
    vehicles = r.get_json().get("vehicles") or []
    assert vehicles
    assert "cv" in vehicles[0]
    assert "video_available" in vehicles[0]["cv"]


def test_fleet_active_toggle_api(client, mock_controller):
    import json

    from web.server import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post(
            "/api/fleet/active/toggle",
            data=json.dumps({"vehicle_id": "rover_2", "active": True}),
            content_type="application/json",
        )
        assert r.status_code == 200
        d = r.get_json()
        assert d["status"] != "error"
        assert "active_vehicle_ids" in d


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
            data=json.dumps({
                "vehicle_id": "rover_2",
                "speed": 1.0,
                "waypoints": v2.mission_waypoints,
            }),
            content_type="application/json",
        )
    assert r.status_code == 200
    assert r.get_json()["vehicle_id"] == "rover_2"
