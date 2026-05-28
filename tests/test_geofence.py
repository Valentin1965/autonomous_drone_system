"""Геозона — bbox."""

from web.geofence import check_position, check_waypoints, reload, set_bounds


def test_geofence_inside(tmp_path, monkeypatch):
    monkeypatch.setattr("web.geofence_store.RUNTIME_PATH", tmp_path / "gf.yaml")
    reload()
    set_bounds(50.44, 50.46, 30.51, 30.53)
    ok, msg = check_position(50.45, 30.52)
    assert ok
    assert msg == ""


def test_geofence_outside(tmp_path, monkeypatch):
    monkeypatch.setattr("web.geofence_store.RUNTIME_PATH", tmp_path / "gf.yaml")
    reload()
    set_bounds(50.44, 50.46, 30.51, 30.53)
    ok, msg = check_position(50.50, 30.52)
    assert not ok


def test_waypoints_in_fence(tmp_path, monkeypatch):
    monkeypatch.setattr("web.geofence_store.RUNTIME_PATH", tmp_path / "gf.yaml")
    reload()
    set_bounds(50.44, 50.46, 30.51, 30.53)
    ok, _ = check_waypoints([{"lat": 50.45, "lon": 30.52}])
    assert ok
