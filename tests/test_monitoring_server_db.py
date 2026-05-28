"""Тести SQLite на віддаленому сервері моніторингу."""

import tempfile
from pathlib import Path

from server import database as db


def test_fleet_events_and_findings():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "test.db"
        db.init_db(path)

        db.insert_fleet_event(
            event_type="mission_run",
            station_id="gcs-1",
            operator="Ivan",
            vehicle_id="rover_1",
            lat=50.45,
            lon=30.52,
            detail="3 waypoints",
            payload={"speed_m_s": 1.0},
        )
        db.insert_capture(
            capture_id="cap01",
            station_id="gcs-1",
            operator="Ivan",
            vehicle_id="rover_1",
            crop="vineyard",
            lat=50.45,
            lon=30.52,
            source="survey",
            left_image_path="a/left.jpg",
            right_image_path="a/right.jpg",
            context={"vehicle": {"sprayer_active": False}},
            analysis_message="ok",
        )
        db.insert_detections(
            "cap01",
            [
                {
                    "camera": "left",
                    "label": "mildew",
                    "confidence": 0.7,
                    "issue_type": "disease",
                    "severity": "medium",
                }
            ],
        )

        ops = db.list_operations(vehicle_id="rover_1")
        assert len(ops) == 1
        assert ops[0]["event_type"] == "mission_run"
        assert ops[0]["operator"] == "Ivan"

        findings = db.list_findings(vehicle_id="rover_1")
        assert len(findings) == 1
        assert findings[0]["label"] == "mildew"
        assert findings[0]["capture_id"] == "cap01"

        st = db.stats()
        assert st["fleet_events"] >= 1
        assert st["monitoring_captures"] == 1
        assert st["monitoring_detections"] == 1
