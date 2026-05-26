"""MissionRunner — forward from wp1, at_last, return, stop."""

import time
from unittest.mock import MagicMock, patch

from web.mission_runner import MissionRunner, _haversine_m


def test_haversine_zero():
    assert _haversine_m(50.45, 30.52, 50.45, 30.52) < 0.01


def test_update_route_waypoints_while_paused():
    runner = MissionRunner()
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
    runner = MissionRunner()
    runner.phase = "running"
    try:
        runner.update_route_waypoints([{"lat": 1.0, "lon": 2.0}])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_forward_starts_at_first_waypoint():
    runner = MissionRunner()
    wps = [
        {"lat": 50.451, "lon": 30.524},
        {"lat": 50.452, "lon": 30.525},
    ]
    ctrl = MagicMock()

    with patch("web.mission_runner.drone_state") as st, patch(
        "simulator.registry.snap_to"
    ) as snap, patch.object(runner, "_follow_path"):
        st.emergency_stop = False
        st.load_config.return_value = {"mission": {"arrival_radius_m": 2.5}}
        st.get_controller.return_value = ctrl
        runner._run_forward(wps)

    snap.assert_called_once_with(50.451, 30.524)
    ctrl.goto_latlon.assert_called_with(50.452, 30.525, speed_m_s=runner.speed_m_s)


def test_start_return_keeps_at_last_phase_until_running():
    runner = MissionRunner()
    runner.phase = "at_last"
    runner._waypoints = [
        {"lat": 50.45, "lon": 30.52},
        {"lat": 50.451, "lon": 30.521},
    ]

    with patch.object(runner, "_run_path"), patch(
        "web.mission_runner.drone_state"
    ) as st:
        st.load_config.return_value = {"mission": {}}
        result = runner.start_return()
    assert result["phase"] == "returning"


def test_pause_sets_phase():
    runner = MissionRunner()
    runner.phase = "running"
    runner._thread = None
    with patch("web.mission_runner.drone_state") as st, patch(
        "web.mission_runner._halt_all_motion"
    ):
        st.get_controller.return_value = MagicMock()
        runner.pause(wait=False)
    assert runner.phase == "paused"


def test_follow_path_stops_at_last_waypoint():
    runner = MissionRunner()
    runner.arrival_m = 2.5
    wps = [
        {"lat": 50.45, "lon": 30.52},
        {"lat": 50.451, "lon": 30.521},
    ]
    runner._waypoints = list(wps)
    ctrl = MagicMock()
    gps = {"lat": 50.451, "lon": 30.521}

    with patch("web.mission_runner._current_gps", return_value=gps), patch(
        "web.mission_runner._halt_all_motion"
    ) as halt, patch("simulator.registry.snap_to") as snap, patch(
        "web.mission_runner.drone_state"
    ) as st:
        st.emergency_stop = False
        st.load_config.return_value = {
            "mission": {"poll_interval_s": 0.01, "goto_retry_s": 10.0},
        }
        runner._follow_path(ctrl, wps, start_index=1, is_return=False)

    assert runner.phase == "at_last"
    halt.assert_called()
    snap.assert_called_with(50.451, 30.521)
    assert runner._stop.is_set()


def test_stop_halts():
    runner = MissionRunner()
    runner.phase = "running"
    with patch("web.mission_runner.drone_state") as st, patch(
        "web.mission_runner._halt_all_motion"
    ) as halt:
        st.get_controller.return_value = MagicMock()
        runner.stop(wait=False)
    assert runner.phase == "aborted"
    halt.assert_called()
