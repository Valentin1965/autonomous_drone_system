"""MAVLink / CV config resolution."""

from mavlink.runtime_config import (
    client_connection_string,
    mavlink_profile,
    simulator_bind_string,
)
from cv.tracker import resolve_video_path, resolve_yolo_device


def test_mavlink_profile_sim_default():
    cfg = {"mavlink": {"active": "sim"}}
    assert mavlink_profile(cfg) == "sim"


def test_client_connection_strings():
    cfg = {
        "mavlink": {
            "active": "sim",
            "connection_sim": "udp:127.0.0.1:14550",
            "connection_px4": "udp:127.0.0.1:14540",
        }
    }
    assert client_connection_string(cfg) == "udp:127.0.0.1:14550"
    assert client_connection_string(cfg, "px4") == "udp:127.0.0.1:14540"


def test_simulator_bind():
    cfg = {"simulator": {"connection_string": "udpin:0.0.0.0:14550"}}
    assert simulator_bind_string(cfg) == "udpin:0.0.0.0:14550"


def test_yolo_device_cpu_env(monkeypatch):
    monkeypatch.setenv("YOLO_DEVICE", "cpu")
    assert resolve_yolo_device({}) == "cpu"


def test_resolve_video_path_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {"video_dir": str(tmp_path / "empty_videos"), "video_file": ""}
    assert resolve_video_path(cfg) == ""


def test_resolve_video_path_from_project_root(tmp_path, monkeypatch):
    from config.config_paths import project_root

    vdir = project_root() / "assets" / "videos"
    demo = vdir / "vineyard_demo.mp4"
    if not demo.is_file():
        return  # відео в .gitignore — локально у користувача
    monkeypatch.chdir(tmp_path)
    cfg = {"video_dir": "assets/videos", "video_file": ""}
    path = resolve_video_path(cfg)
    assert path.endswith("vineyard_demo.mp4")
