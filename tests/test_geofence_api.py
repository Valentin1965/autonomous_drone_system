"""API геозони оператора."""

import pytest

from web.geofence import is_enabled, reload


@pytest.fixture
def geofence_runtime(tmp_path, monkeypatch):
    path = tmp_path / "geofence_runtime.yaml"
    monkeypatch.setattr("web.geofence_store.RUNTIME_PATH", path)
    reload()
    yield path
    reload()


def test_put_geofence(client, geofence_runtime):
    r = client.put(
        "/api/geofence",
        json={
            "enabled": True,
            "min_lat": 50.44,
            "max_lat": 50.46,
            "min_lon": 30.51,
            "max_lon": 30.53,
        },
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is True
    assert d["operator_set"] is True
    reload()
    assert is_enabled()


def test_from_route(client, mock_controller, geofence_runtime):
    client.post("/api/mission/clear")
    client.post("/api/mission/waypoint", json={"lat": 50.45, "lon": 30.52})
    client.post("/api/mission/waypoint", json={"lat": 50.451, "lon": 30.525})
    r = client.post("/api/geofence/from-route", json={"padding_m": 20})
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is True
    assert d["min_lat"] < 50.45 < d["max_lat"]


def test_waypoint_outside_geofence(client, mock_controller, geofence_runtime):
    client.put(
        "/api/geofence",
        json={
            "enabled": True,
            "min_lat": 50.44,
            "max_lat": 50.46,
            "min_lon": 30.51,
            "max_lon": 30.53,
        },
    )
    reload()
    client.post("/api/control/mode/autonomous")
    r = client.post("/api/mission/waypoint", json={"lat": 50.50, "lon": 30.52})
    assert r.status_code == 400
    assert r.get_json().get("error") == "geofence"
