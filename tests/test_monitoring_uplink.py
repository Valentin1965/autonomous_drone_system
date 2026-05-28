"""RPi uplink: POST /api/monitoring/upload та станція."""

import io
import json

import pytest

from web.server import app


@pytest.fixture
def rpi_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITORING_CONFIG", "config/monitoring.field.yaml")
    from monitoring import config_loader
    from monitoring.rpi_uplink import clear_buffer
    from monitoring.service import reset_monitoring_service

    config_loader._CACHE = None
    reset_monitoring_service()
    clear_buffer()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    clear_buffer()
    reset_monitoring_service()
    config_loader._CACHE = None


def test_monitoring_upload_stores_stereo(rpi_client):
    import cv2
    import numpy as np

    from monitoring.rpi_uplink import buffer_status, wait_stereo

    def _jpeg():
        img = np.zeros((48, 64, 3), dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        return buf.tobytes()

    for side in ("left", "right"):
        r = rpi_client.post(
            "/api/monitoring/upload",
            data={
                "vehicle_id": "rover_1",
                "side": side,
                "image": (io.BytesIO(_jpeg()), f"{side}.jpg"),
            },
            content_type="multipart/form-data",
        )
        assert r.status_code == 200, r.get_json()

    st = buffer_status("rover_1")
    assert st.get("left") and st.get("right")

    stereo = wait_stereo("rover_1", timeout_s=1.0)
    assert stereo.left.frame is not None
    assert stereo.right.frame is not None


def test_monitoring_upload_rejected_when_local(client, monkeypatch):
    monkeypatch.setenv("MONITORING_CONFIG", "config/monitoring.dev.yaml")
    from monitoring import config_loader

    config_loader._CACHE = None
    r = client.post(
        "/api/monitoring/upload",
        data={
            "vehicle_id": "rover_1",
            "side": "left",
            "image": (io.BytesIO(b"jpeg"), "a.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 409
    assert r.get_json().get("error") == "uplink_not_rpi"


def test_monitoring_station_put_get(rpi_client, tmp_path, monkeypatch):
    runtime = tmp_path / "monitoring_runtime.yaml"
    monkeypatch.setattr("monitoring.station_config.runtime_path", lambda: runtime)
    from monitoring import config_loader

    config_loader._CACHE = None

    r = rpi_client.put(
        "/api/monitoring/station",
        data=json.dumps({"station_id": "field-1", "operator": "Test Op"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["station_id"] == "field-1"
    assert body["operator"] == "Test Op"

    r2 = rpi_client.get("/api/monitoring/station")
    assert r2.status_code == 200
    assert r2.get_json()["operator"] == "Test Op"


def test_monitoring_preflight_api(client, mock_controller):
    from unittest.mock import patch

    mock_controller.get_status.return_value = {
        "connected": True,
        "armed": True,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch("web.preflight._sim_active", return_value=True):
        with patch("web.geofence.is_enabled", return_value=False):
            r = client.get("/api/monitoring/preflight?vehicle_id=rover_1")
    assert r.status_code == 200
    assert r.get_json().get("ready_for_cv") is True
