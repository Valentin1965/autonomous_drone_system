"""Тести GPS-треку оприскування та агрегації на сервері."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

from monitoring.spray_coverage import on_sprayer_transition, reset_totals, vehicle_summary
from monitoring.spray_geo import area_from_path_m2, haversine_m, path_length_m
from server import database as db
from server import spray_coverage as server_spray


def test_haversine_and_area():
    # ~111 м на градус широти
    d = haversine_m(50.0, 30.0, 50.001, 30.0)
    assert 100 < d < 120
    pts = [(50.0, 30.0), (50.001, 30.0), (50.002, 30.0)]
    length = path_length_m(pts)
    area = area_from_path_m2(length, 2.0)
    assert length > 200
    assert area == length * 2.0


def test_sprayer_session_metrics(monkeypatch):
    reset_totals()
    v = MagicMock()
    v.id = "rover_1"
    v.sprayer_active = True

    positions = [(50.45, 30.52), (50.4501, 30.52), (50.4502, 30.52)]

    def gps_side_effect(_v):
        if positions:
            lat, lon = positions.pop(0)
            return lat, lon
        return 50.4502, 30.52

    import monitoring.spray_coverage as sc

    monkeypatch.setattr(sc, "_gps_for_vehicle", gps_side_effect)

    on_sprayer_transition(v, True, source="test", uplink=False)
    time.sleep(0.05)
    sc.tick_vehicle(v)
    metrics = on_sprayer_transition(v, False, source="test", uplink=False)
    assert metrics is not None
    assert metrics["path_length_m"] >= 0
    assert metrics["area_m2"] >= 0
    assert metrics["duration_s"] >= 0

    summary = vehicle_summary("rover_1")
    assert summary["totals"]["session_count"] == 1
    reset_totals()


def test_server_spray_sessions_from_events():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "spray.db"
        db.init_db(path)
        db.insert_fleet_event(
            event_type="sprayer_on",
            station_id="gcs-1",
            vehicle_id="rover_1",
            lat=50.45,
            lon=30.52,
            detail="on",
            payload={"spray_source": "manual"},
        )
        db.insert_fleet_event(
            event_type="sprayer_off",
            station_id="gcs-1",
            vehicle_id="rover_1",
            lat=50.451,
            lon=30.52,
            detail="off",
            payload={
                "spray_coverage": {
                    "session_id": "abc",
                    "path_length_m": 120.5,
                    "area_m2": 241.0,
                    "area_ha": 0.0241,
                    "duration_s": 45.0,
                    "swath_width_m": 2.0,
                }
            },
        )
        summary = server_spray.coverage_summary(vehicle_id="rover_1")
        assert summary["session_count"] == 1
        assert summary["total_area_m2"] == 241.0
        assert summary["sessions"][0]["from_payload"] is True
