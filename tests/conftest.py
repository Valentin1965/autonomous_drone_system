"""Shared pytest fixtures — reset singletons between tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_app_state(monkeypatch):
    from web import state as web_state
    from web import tracker_service

    import web.fleet as fm

    fm._fleet = None
    web_state.drone_state._controller = None
    web_state.drone_state._cfg = None
    # sprayer_active делегує до get_fleet().selected — лише після скидання _fleet
    try:
        from web.fleet import get_fleet

        fleet = get_fleet()
        if fleet.vehicles:
            fleet.selected.sprayer_active = False
    except Exception:
        pass

    try:
        from simulator.fleet_registry import unregister_all

        unregister_all()
    except Exception:
        pass
    try:
        from simulator.registry import unregister

        unregister()
    except Exception:
        pass

    tracker_service._tracker = None
    try:
        from web.geofence import reload

        reload()
    except Exception:
        pass
    try:
        from monitoring.service import reset_monitoring_service

        reset_monitoring_service()
    except Exception:
        pass
    try:
        from monitoring import config_loader

        config_loader._CACHE = None
    except Exception:
        pass

    monkeypatch.setattr(
        "monitoring.offline_queue.ensure_worker_started",
        lambda: None,
    )
    # Не запускати MAVLink-телеметрію в потоках під час pytest
    monkeypatch.setattr(
        "mavlink.ground_controller.GroundController._start_telemetry_thread",
        lambda self: None,
    )

    yield

    fm._fleet = None
    try:
        from simulator.fleet_registry import unregister_all

        unregister_all()
    except Exception:
        pass
    try:
        from simulator.registry import unregister

        unregister()
    except Exception:
        pass


@pytest.fixture
def client():
    from web.server import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def mock_controller(monkeypatch):
    """
    Mock MAVLink для обраного дрона флоту + SimStub у fleet_registry.
    Уникає реального UDP/serial під час API-тестів.
    """
    from simulator.fleet_registry import register_vehicle, unregister_all
    from simulator.sim_stub import SimStub
    from web.fleet import get_fleet
    import web.fleet as fm

    unregister_all()
    fm._fleet = None

    ctrl = MagicMock()
    ctrl.frame = "body"
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": False,
        "frame": "body",
        "connection": "udp:127.0.0.1:14550",
        "heartbeat_age_s": 0.5,
        "reconnecting": False,
        "velocity_cmd": {"forward": 0, "lateral": 0, "yaw": 0},
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    ctrl.arm = MagicMock()
    ctrl.disarm = MagicMock()
    ctrl.stop = MagicMock()
    ctrl.set_velocity = MagicMock()
    ctrl.set_frame = MagicMock()
    ctrl.ensure_connected = MagicMock()
    ctrl.goto_latlon = MagicMock()

    from simulator.registry import register as registry_register

    fleet = get_fleet()
    primary_stub = None
    for vid, v in fleet.vehicles.items():
        stub = SimStub(v.start_lat, v.start_lon)
        register_vehicle(vid, stub)
        if vid == fleet.selected_id:
            primary_stub = stub
        v._controller = ctrl
        v.control_mode = "manual"
    if primary_stub is not None:
        registry_register(primary_stub)

    monkeypatch.setattr(
        "web.vehicle.GroundController",
        lambda *a, **k: ctrl,
        raising=False,
    )

    yield ctrl

    unregister_all()
    fm._fleet = None


@pytest.fixture
def mock_vehicle():
    """Мінімальний Vehicle для unit-тестів MissionRunner."""
    v = MagicMock()
    v.id = "rover_1"
    v.mission_waypoints = []
    return v


@pytest.fixture
def analysis_server(tmp_path, monkeypatch):
    """
    server.main in-process (без YOLO weights) — для remote.mode: remote у тестах.
    """
    import threading

    from werkzeug.serving import make_server

    from tests.helpers_monitoring import free_port

    monkeypatch.setenv("MONITORING_API_KEY", "")
    monkeypatch.setenv("YOLO_DEVICE", "cpu")
    monkeypatch.setenv("YOLO_CONF", "0.01")
    monkeypatch.setenv("MONITORING_DEFAULT_WEIGHTS", "")
    monkeypatch.setenv("MONITORING_VINEYARD_WEIGHTS", "")
    monkeypatch.setenv("MONITORING_BANANA_WEIGHTS", "")

    from server import config as scfg
    from server import database as sdb
    from server import yolo_engine as yolo
    from server.app import app

    scfg._CACHE = None
    db_path = tmp_path / "fleet.db"
    sdb.init_db(db_path)
    yolo.setup("cpu", 0.01, {})

    port = free_port()
    httpd = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"base_url": f"http://127.0.0.1:{port}", "db_path": db_path, "port": port}
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass
