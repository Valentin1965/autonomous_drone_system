"""MissionRunner — forward from wp1, at_last, return, stop."""

from unittest.mock import MagicMock, patch

from web.mission_runner import MissionRunner, _haversine_m
from web.vehicle import Vehicle


def test_haversine_zero():
    assert _haversine_m(50.45, 30.52, 50.45, 30.52) < 0.01


def _vehicle_with_ctrl(ctrl):
    v = Vehicle(
        vehicle_id="rover_1",
        name="Rover 1",
        mavlink_connection="udp:127.0.0.1:14550",
    )
    v._controller = ctrl
    return v


def test_update_route_waypoints_while_paused():
    v = _vehicle_with_ctrl(MagicMock())
    runner = MissionRunner(v)
    runner.phase = "paused"
    runner._waypoints = [{"lat": 1.0, "lon": 2.0}]
    runner.index = 0
    runner.total = 1
    new_wps = [
        {"lat": 1.0, "lon": 2.0},
        {"lat": 3.0, "lon": 4.0},
    ]
    runner.update_route_waypoints(new_wps)
    assert len(runner._waypoints) == 2
    assert runner.total == 2


def test_update_route_waypoints_blocked_while_running():
    v = _vehicle_with_ctrl(MagicMock())
    runner = MissionRunner(v)
    runner.phase = "running"
    try:
        runner.update_route_waypoints([{"lat": 1.0, "lon": 2.0}])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_forward_starts_at_first_waypoint():
    ctrl = MagicMock()
    v = _vehicle_with_ctrl(ctrl)
    runner = MissionRunner(v)
    wps = [
        {"lat": 50.451, "lon": 30.524},
        {"lat": 50.452, "lon": 30.525},
    ]

    runner.phase = "running"
    with patch("web.mission_runner.get_fleet") as gf, patch(
        "simulator.fleet_registry.snap_to"
    ) as snap, patch.object(runner, "_follow_path"):
        fleet = MagicMock()
        fleet.emergency_stop = False
        gf.return_value = fleet
        runner._run_forward(wps)

    snap.assert_called_once_with(50.451, 30.524, "rover_1")
    ctrl.goto_latlon.assert_called_with(50.452, 30.525, speed_m_s=runner.speed_m_s)


def test_start_return_keeps_at_last_phase_until_running():
    v = _vehicle_with_ctrl(MagicMock())
    runner = MissionRunner(v)
    runner.phase = "at_last"
    runner._waypoints = [
        {"lat": 50.45, "lon": 30.52},
        {"lat": 50.451, "lon": 30.521},
    ]

    with patch.object(runner, "_run_path"), patch(
        "web.mission_runner.get_fleet"
    ) as gf:
        gf.return_value.load_config.return_value = {"mission": {}}
        result = runner.start_return()
    assert result["phase"] == "returning"


def test_pause_sets_phase():
    ctrl = MagicMock()
    v = _vehicle_with_ctrl(ctrl)
    runner = MissionRunner(v)
    runner.phase = "running"
    runner._thread = None
    with patch("web.mission_runner.get_fleet") as gf:
        gf.return_value.emergency_stop = False
        runner.pause(wait=False)
    assert runner.phase == "paused"


def test_follow_path_stops_at_last_waypoint():
    ctrl = MagicMock()
    v = _vehicle_with_ctrl(ctrl)
    runner = MissionRunner(v)
    runner.arrival_m = 2.5
    wps = [
        {"lat": 50.45, "lon": 30.52},
        {"lat": 50.451, "lon": 30.521},
    ]
    runner._waypoints = list(wps)
    gps = {"lat": 50.451, "lon": 30.521}

    with patch("web.mission_runner._current_gps", return_value=gps), patch(
        "web.mission_runner._halt_vehicle_motion"
    ) as halt, patch("simulator.fleet_registry.snap_to") as snap, patch(
        "web.mission_runner.get_fleet"
    ) as gf, patch("web.geofence.is_enabled", return_value=False):
        fleet = MagicMock()
        fleet.emergency_stop = False
        gf.return_value = fleet
        runner._follow_path(ctrl, wps, start_index=1, is_return=False)

    assert runner.phase == "at_last"
    halt.assert_called()
    snap.assert_called_with(50.451, 30.521, "rover_1")
    assert runner._stop.is_set()


def test_stop_halts():
    ctrl = MagicMock()
    v = _vehicle_with_ctrl(ctrl)
    runner = MissionRunner(v)
    runner.phase = "running"
    with patch("web.mission_runner._halt_vehicle_motion") as halt:
        runner.stop(wait=False)
    assert runner.phase == "aborted"
    halt.assert_called()
