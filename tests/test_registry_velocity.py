"""Ручний рух через registry.apply_manual_velocity."""

import time

from simulator.pixhawk_simulator import PixhawkGPSSimulator
from simulator.registry import (
    DEFAULT_SIM_LAT,
    DEFAULT_SIM_LON,
    apply_manual_velocity,
    get_position,
    is_default_sim_position,
    register,
    snap_to,
    snap_to_start_waypoint_if_needed,
)


def test_manual_velocity_moves_rover():
    sim = PixhawkGPSSimulator("udpin:127.0.0.1:0")
    register(sim)
    snap_to(50.45, 30.52)
    apply_manual_velocity(0.8, 0.0, frame="body")
    lon0 = sim.lon
    for _ in range(25):
        sim.update_position(dt=0.2)
    assert sim.lon > lon0
    pos = get_position()
    assert pos is not None
    sim.running = False


def test_snap_to_start_only_when_default_center():
    sim = PixhawkGPSSimulator("udpin:127.0.0.1:0")
    register(sim)
    wps = [{"lat": 50.46, "lon": 30.54}]
    assert is_default_sim_position(get_position())
    assert snap_to_start_waypoint_if_needed(wps) is True
    pos = get_position()
    assert abs(pos["lat"] - 50.46) < 1e-6
    assert snap_to_start_waypoint_if_needed(wps) is False
    snap_to(50.47, 30.55)
    assert not is_default_sim_position(get_position())
    assert snap_to_start_waypoint_if_needed(wps) is True
    assert abs(get_position()["lat"] - 50.46) < 1e-6
    assert snap_to_start_waypoint_if_needed(wps) is False
    sim.running = False
