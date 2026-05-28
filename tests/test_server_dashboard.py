"""HTTP-дашборд analysis server."""

import tempfile
from pathlib import Path

from server import database as db
from server.app import app


def test_dashboard_page():
    with app.test_client() as client:
        r = client.get("/dashboard")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Fleet Analysis Server" in html
        assert "findingsBody" in html
        assert "operationsBody" in html


def test_dashboard_api_json_with_data():
    with tempfile.TemporaryDirectory() as td:
        db.init_db(Path(td) / "dash.db")
        db.insert_fleet_event(
            event_type="mission_run",
            station_id="gcs-1",
            operator="Op",
            vehicle_id="rover_1",
            lat=50.45,
            lon=30.52,
            detail="test",
            payload={},
        )
        with app.test_client() as client:
            r = client.get("/api/v1/operations?limit=5")
            assert r.status_code == 200
            data = r.get_json()
            assert data["count"] == 1
            assert data["operations"][0]["event_type"] == "mission_run"
