"""Дві камери + віддалений (mock) аналіз."""

import json

import numpy as np
import pytest

from monitoring.analyzer import analyze_point
from monitoring.cameras import DualCameraRig, get_camera_rig
from monitoring.remote_client import analyze_stereo_remote, check_remote_health
from monitoring.store import clear_findings


@pytest.fixture(autouse=True)
def _reset_rig():
    from monitoring.service import reset_monitoring_service

    reset_monitoring_service()
    clear_findings()
    yield
    reset_monitoring_service()


def test_stereo_synthetic_capture():
    rig = DualCameraRig()
    try:
        cap = rig.capture_stereo()
        assert cap.left.frame is not None
        assert cap.right.frame is not None
        assert cap.left.jpeg and cap.right.jpeg
    finally:
        rig.release()


def test_mock_remote_analysis(monkeypatch):
    monkeypatch.setenv("SYSTEM_CONFIG", "config/system.yaml")
    from monitoring import config_loader

    config_loader._CACHE = None
    cfg = config_loader.load_monitoring_config(reload=True)
    cfg["remote"]["mode"] = "mock"
    cfg["demo_findings_in_sim"] = True
    config_loader._CACHE = cfg

    rig = get_camera_rig(reload=True)
    stereo = rig.capture_stereo()
    result = analyze_stereo_remote(
        stereo,
        crop="vineyard",
        vehicle_id="rover_1",
        lat=50.45,
        lon=30.52,
        demo_sim=True,
    )
    assert result.remote_ok
    assert len(result.detections) >= 1
    assert result.detections[0].camera_side in ("left", "right", "")


def test_analyze_point_integration(monkeypatch):
    from monitoring import config_loader

    cfg = config_loader.load_monitoring_config(reload=True)
    cfg["remote"]["mode"] = "mock"
    cfg["demo_findings_in_sim"] = True
    config_loader._CACHE = cfg
    get_camera_rig(reload=True)

    result = analyze_point(
        crop="vineyard",
        vehicle_id="rover_1",
        lat=50.45,
        lon=30.52,
        source="manual",
    )
    assert result.remote_ok


def test_mock_health():
    from monitoring import config_loader

    cfg = config_loader.load_monitoring_config(reload=True)
    cfg["remote"]["mode"] = "mock"
    config_loader._CACHE = cfg
    h = check_remote_health()
    assert h["ok"] is True


def test_monitoring_config_includes_cameras(client):
    r = client.get("/api/monitoring/config")
    data = r.get_json()
    assert "cameras" in data
    assert data["cameras"]["left"]
    assert data["architecture"] == "dual_camera_remote_yolo"
