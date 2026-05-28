"""Preflight та emergency reset."""

from unittest.mock import MagicMock, patch

import pytest

from web.preflight import assert_ready_for_mission, evaluate


def test_preflight_ok_without_geofence_when_disabled():
    v = MagicMock()
    v.id = "rover_1"
    v.mission_waypoints = [{"lat": 50.45, "lon": 30.52}]
    st = {
        "connected": True,
        "armed": True,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch("web.fleet.get_fleet") as gf:
        fleet = MagicMock()
        fleet.emergency_stop = False
        gf.return_value = fleet
        with patch("web.geofence.is_enabled", return_value=False):
            pf = evaluate(v, mavlink_status=st, require_route=True)
    assert pf["ready_for_mission"]
    assert pf["checks"]["geofence"]["ok"]


def test_preflight_sim_allows_without_prior_arm():
    v = MagicMock()
    v.id = "rover_1"
    v.mission_waypoints = [{"lat": 50.45, "lon": 30.52}]
    st = {
        "connected": False,
        "armed": False,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch("web.fleet.get_fleet") as gf:
        fleet = MagicMock()
        fleet.emergency_stop = False
        gf.return_value = fleet
        with patch("web.geofence.is_enabled", return_value=False):
            with patch("web.preflight._sim_active", return_value=True):
                pf = evaluate(v, mavlink_status=st, require_route=True)
    assert pf["ready_for_mission"]


def test_preflight_blocks_without_arm():
    v = MagicMock()
    v.id = "rover_1"
    v.mission_waypoints = [{"lat": 50.45, "lon": 30.52}]
    st = {
        "connected": True,
        "armed": False,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch("web.fleet.get_fleet") as gf:
        fleet = MagicMock()
        fleet.emergency_stop = False
        gf.return_value = fleet
        with patch("web.geofence.is_enabled", return_value=False):
            pf = evaluate(v, mavlink_status=st, require_route=True)
    assert not pf["ready_for_mission"]
    assert not pf["checks"]["armed"]["ok"]


def test_emergency_reset_api(client, mock_controller):
    from web.fleet import get_fleet

    get_fleet().emergency_stop = True
    r = client.post("/api/emergency/reset")
    assert r.status_code == 200
    assert r.get_json()["emergency_stop"] is False
    assert get_fleet().emergency_stop is False


def test_mission_run_preflight_409(client, mock_controller):
    mock_controller.get_status.return_value = {
        "connected": True,
        "armed": False,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    client.post("/api/control/mode/autonomous")
    client.post("/api/mission/clear")
    client.post("/api/mission/waypoint", json={"lat": 50.45, "lon": 30.52})
    client.post("/api/mission/waypoint", json={"lat": 50.451, "lon": 30.525})
    with patch("web.preflight._sim_active", return_value=False):
        with patch("web.geofence.is_enabled", return_value=True):
            with patch("web.preflight.geofence.is_enabled", return_value=True):
                with patch(
                    "web.preflight.geofence.check_waypoints", return_value=(True, "")
                ):
                    with patch(
                        "web.preflight.geofence.check_position",
                        return_value=(True, ""),
                    ):
                        r = client.post("/api/mission/run", json={"speed": 1.0})
    assert r.status_code == 409
    assert r.get_json().get("error") == "preflight_failed"
