"""Планувальник рядів: ENU → lat/lon → gcs_mission_v2."""

import json
import math

import pytest

from planning.field_plan import FieldPlanRequest, plan_vineyard_field
from planning.mission_waypoints import (
    build_parallel_row_lines,
    lines_to_latlon_waypoints,
    strip_roles,
)
from web.mission_record import MISSION_FORMAT_V2
from web.server import app


@pytest.fixture(autouse=True)
def reset_fleet():
    import web.fleet as fm

    fm._fleet = None
    yield
    fm._fleet = None


def test_parallel_rows_spacing_1m():
    """Міжряддя 1 m у ENU; у WGS84 — без zigzag (zigzag міняє який кінець ряду «row_start»)."""
    origin_lat, origin_lon = 28.2916, -16.6291
    lines = build_parallel_row_lines(
        row_count=3,
        row_length_m=10.0,
        row_spacing_m=1.0,
        azimuth_deg=0.0,
    )
    for i in range(1, len(lines)):
        e0, n0 = lines[i - 1].coords[0]
        e1, n1 = lines[i].coords[0]
        assert math.hypot(e1 - e0, n1 - n0) == pytest.approx(1.0, abs=0.01)

    wps = lines_to_latlon_waypoints(
        lines, origin_lat, origin_lon, use_zigzag=False, add_turn_points=False
    )
    assert len(wps) == 6
    starts = [w for w in wps if w["role"] == "row_start"]
    assert len(starts) == 3
    # Азимут 0°: ряд на північ, міжряддя — на схід (lon)
    m_per_deg_lon = 111320.0 * math.cos(math.radians(origin_lat))
    lons = [s["lon"] for s in starts]
    d01 = abs(lons[1] - lons[0]) * m_per_deg_lon
    d12 = abs(lons[2] - lons[1]) * m_per_deg_lon
    assert d01 == pytest.approx(1.0, abs=0.05)
    assert d12 == pytest.approx(1.0, abs=0.05)


def test_zigzag_reverses_alternate_rows():
    lines = build_parallel_row_lines(2, 20.0, 2.0, azimuth_deg=90.0)
    wps = lines_to_latlon_waypoints(
        lines, 50.0, 30.0, use_zigzag=True, add_turn_points=False
    )
    row0_end = next(w for w in wps if w.get("row_index") == 0 and w["role"] == "row_end")
    row1_end = next(w for w in wps if w.get("row_index") == 1 and w["role"] == "row_end")
    assert row0_end["lon"] != row1_end["lon"]


def test_plan_vineyard_gcs_v2_format():
    req = FieldPlanRequest(
        origin_lat=28.2916,
        origin_lon=-16.6291,
        row_count=2,
        row_length_m=30.0,
        row_spacing_m=1.0,
        vehicle_id="rover_1",
    )
    out = plan_vineyard_field(req)
    gcs = out["gcs_mission"]
    assert gcs["format"] == MISSION_FORMAT_V2
    assert len(gcs["waypoints"]) >= 4
    assert gcs.get("planning", {}).get("row_spacing_m") == 1.0
    assert len(gcs.get("segments", [])) >= 3
    nav = strip_roles(out["waypoints"])
    assert all("role" not in wp for wp in nav)
    assert nav[0]["lat"] == pytest.approx(28.2916, abs=1e-4)


def test_plan_rows_api_preview(client, mock_controller):
    body = {
        "origin_lat": 28.2916,
        "origin_lon": -16.6291,
        "row_count": 3,
        "row_length_m": 20.0,
        "row_spacing_m": 1.0,
        "apply": False,
    }
    r = client.post(
        "/api/mission/plan-rows",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("store_draft") is False
    assert data.get("route_committed") is False
    assert data["stats"]["waypoint_count"] >= 6
    assert data["gcs_mission"]["format"] == MISSION_FORMAT_V2


def test_plan_rows_api_store_draft_not_committed(client, mock_controller):
    body = {
        "origin_lat": 28.2916,
        "origin_lon": -16.6291,
        "row_count": 2,
        "row_length_m": 15.0,
        "row_spacing_m": 1.0,
        "store_draft": True,
    }
    r = client.post(
        "/api/mission/plan-rows",
        data=json.dumps(body),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["store_draft"] is True
    assert data["route_committed"] is False
    r2 = client.get("/api/mission")
    m = r2.get_json()
    assert m["waypoints"] == []
    assert len(m["draft"]["waypoints"]) == data["stats"]["waypoint_count"]


def test_plan_defaults_api(client, mock_controller):
    r = client.get("/api/mission/plan/defaults")
    assert r.status_code == 200
    d = r.get_json()
    assert d["row_spacing_m"] == 1.0
    assert "navigation_note" in d
