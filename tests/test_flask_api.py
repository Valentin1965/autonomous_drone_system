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


def test_halt_preserves_mission(client, mock_controller):
    with patch("web.mission_runner.mission_runner") as mr:
        mr.active = True
        r = client.post("/api/halt")
    assert r.status_code == 200
    assert r.get_json().get("mission_preserved") is True
    mock_controller.stop.assert_called_once()
    mr.stop.assert_not_called()


def test_move_blocked_not_manual(client, mock_controller):
    from web.state import drone_state

    drone_state.set_control_mode("autonomous")
    r = client.post("/api/move", json={"forward": 0.5, "lateral": 0})
    assert r.status_code == 409
    mock_controller.set_velocity.assert_not_called()


def test_move_allowed_in_manual(client, mock_controller):
    from web.state import drone_state

    drone_state.set_control_mode("manual")
    with patch("web.mission_runner.mission_runner") as mr, patch(
        "simulator.registry.get_sim"
    ) as gs, patch("simulator.registry.apply_manual_velocity", return_value=True), patch(
        "simulator.registry.arm_sim", return_value=True
    ):
        mr.active = False
        gs.return_value = object()
        r = client.post("/api/move", json={"forward": 0.5, "lateral": 0})
    assert r.status_code == 200
    assert r.get_json().get("drive") == "simulator"


def test_control_mode_manual_pauses(client, mock_controller):
    from web.mission_runner import mission_runner
    from web.state import drone_state

    drone_state.set_control_mode("autonomous")
    with patch.object(mission_runner, "active", True):
        with patch.object(mission_runner, "pause") as pause:
            r = client.post("/api/control/mode/manual")
    assert r.status_code == 200
    assert r.get_json()["mode"] == "manual"
    pause.assert_called_once()
    assert drone_state.get_control_mode() == "manual"


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


def test_mission_settings(client):
    r = client.get("/api/mission/settings")
    assert r.status_code == 200
    data = r.get_json()
    assert "min_speed_m_s" in data
    assert "max_speed_m_s" in data
    assert data["min_speed_m_s"] <= data["default_speed_m_s"] <= data["max_speed_m_s"]


def test_mission_waypoints(client):
    r = client.post("/api/mission/clear")
    assert r.status_code == 200
    r = client.post("/api/mission/waypoint", json={"lat": 50.45, "lon": 30.52})
    assert r.status_code == 200
    assert r.get_json()["count"] == 1
    r = client.get("/api/mission")
    assert len(r.get_json()["waypoints"]) == 1
    r = client.put("/api/mission/waypoint/0", json={"lat": 50.46, "lon": 30.53})
    assert r.status_code == 200
    assert r.get_json()["waypoint"]["lat"] == 50.46
    r = client.delete("/api/mission/waypoint/0")
    assert r.status_code == 200
    assert r.get_json()["count"] == 0
    r = client.post("/api/mission/clear")
    assert r.get_json()["count"] == 0


def test_mission_edit_blocked_while_running(client):
    from web.mission_runner import mission_runner

    client.post("/api/mission/clear")
    client.post("/api/mission/waypoint", json={"lat": 50.45, "lon": 30.52})
    with patch.object(mission_runner, "status", return_value={"phase": "running"}):
        r = client.post("/api/mission/waypoint", json={"lat": 50.47, "lon": 30.54})
    assert r.status_code == 409
    assert r.get_json().get("error") == "mission_active"


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


@pytest.mark.slow
def test_cv_start_synthetic(client, mock_controller):
    """CV стартує без .mp4 (synthetic) — не блокує Flask."""
    pytest.importorskip("cv2")
    from unittest.mock import patch

    from web.tracker_service import reset_tracker

    reset_tracker()
    cfg = {
        "planner": "hybrid",
        "source": "video",
        "fallback_to_synthetic": True,
        "video_file": "",
        "video_dir": "assets/videos",
        "yolo_device": "cpu",
        "stream_fps": 8,
        "motion": {},
        "display": {"show_window": False},
    }
    with patch("cv.tracker.load_cv_config", return_value=cfg):
        with patch(
            "cv.tracker.YOLOSegmentationTracker._load_yolo_model",
            return_value=False,
        ):
            r = client.post("/api/cv/start")
    try:
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("started", "already_running")
        assert data.get("source") == "synthetic"
        r2 = client.get("/api/cv/status")
        assert r2.get_json().get("running") is True
        snap = client.get("/api/cv/snapshot")
        assert snap.status_code == 200
        assert len(snap.data) > 200
    finally:
        client.post("/api/cv/stop")
        reset_tracker()


def test_sprayer_on(client):
    r = client.post("/api/sprayer/on")
    assert r.status_code == 200
    assert r.get_json()["sprayer"] == "on"
