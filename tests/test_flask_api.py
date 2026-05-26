"""Flask REST API — motion, telemetry, CV status (MAVLink mocked)."""

import pytest
from unittest.mock import MagicMock, patch

from web.server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def mock_controller():
    ctrl = MagicMock()
    ctrl.frame = "body"
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": False,
        "frame": "body",
        "connection": "udp:127.0.0.1:14550",
        "velocity_cmd": {"forward": 0, "lateral": 0, "yaw": 0},
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch("web.state.drone_state.get_controller", return_value=ctrl):
        yield ctrl


def test_arm(client, mock_controller):
    r = client.post("/api/arm")
    assert r.status_code == 200
    assert r.get_json()["armed"] is True
    mock_controller.arm.assert_called_once()


def test_disarm(client, mock_controller):
    r = client.post("/api/disarm")
    assert r.status_code == 200
    mock_controller.disarm.assert_called_once()


def test_move(client, mock_controller):
    r = client.post(
        "/api/move",
        json={"forward": 0.5, "lateral": 0.0, "yaw": 0.0},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["forward"] == 0.5
    mock_controller.set_velocity.assert_called_with(0.5, 0.0, 0.0)


def test_stop(client, mock_controller):
    r = client.post("/api/stop")
    assert r.status_code == 200
    mock_controller.stop.assert_called_once()


def test_status(client, mock_controller):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.get_json()
    assert data["connected"] is True
    assert "gps" in data
    assert data["cv_running"] is False
    assert data["vehicle_type"] == "ground_rover"
    assert data.get("gps_source") in ("mavlink", "simulator", None)


def test_gcs_page(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Leaflet" in html or "leaflet" in html
    assert "/static/js/gcs.js" in html
    assert "cvOverlay" in html


def test_cv_snapshot(client):
    r = client.get("/api/cv/snapshot")
    assert r.status_code == 200
    assert r.mimetype == "image/jpeg"
    assert len(r.data) > 50


def test_mission_waypoints(client):
    r = client.post("/api/mission/clear")
    assert r.status_code == 200
    r = client.post("/api/mission/waypoint", json={"lat": 50.45, "lon": 30.52})
    assert r.status_code == 200
    assert r.get_json()["count"] == 1
    r = client.get("/api/mission")
    assert len(r.get_json()["waypoints"]) == 1
    r = client.post("/api/mission/clear")
    assert r.get_json()["count"] == 0


def test_set_mode(client, mock_controller):
    r = client.post("/api/set_mode", json={"mode": "earth"})
    assert r.status_code == 200
    mock_controller.set_frame.assert_called_with("earth")


def test_cv_status_idle(client):
    r = client.get("/api/cv/status")
    assert r.status_code == 200
    data = r.get_json()
    assert data["running"] is False
    assert data["motion"] is None


def test_sprayer_on(client):
    r = client.post("/api/sprayer/on")
    assert r.status_code == 200
    assert r.get_json()["sprayer"] == "on"
