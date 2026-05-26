"""Pixhawk GPS simulator — velocity setpoints and position integration."""

import socket
import time
from types import SimpleNamespace

import pytest
from pymavlink import mavutil

from simulator.pixhawk_simulator import PixhawkGPSSimulator


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def sim():
    port = _free_udp_port()
    s = PixhawkGPSSimulator(f"udpin:127.0.0.1:{port}")
    yield s
    s.running = False
    time.sleep(0.05)


def test_velocity_setpoint_activates_guided(sim):
    msg = SimpleNamespace(
        target_system=1,
        coordinate_frame=mavutil.mavlink.MAV_FRAME_BODY_NED,
        vx=0.5,
        vy=0.0,
    )
    sim.handle_set_position_target_local_ned(msg)
    assert sim.guided_active is True
    assert sim.target_speed >= 0.5
    assert sim.armed is True
    assert sim.mode == "GUIDED"


def test_update_position_moves_lon_at_heading_90(sim):
    sim.armed = True
    sim.heading = 90.0
    sim.speed = 1.0
    lon_before = sim.lon
    sim.update_position(dt=1.0)
    assert sim.lon > lon_before


def test_arm_command_long(sim):
    msg = SimpleNamespace(
        command=mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        param1=1,
    )
    sim.handle_command_long(msg)
    assert sim.armed is True


def test_sim_exposes_position(sim):
    sim.armed = True
    sim.speed = 1.0
    sim.heading = 90.0
    lon0 = sim.lon
    sim.update_position(dt=1.0)
    pos = sim.get_position()
    assert pos["lon"] > lon0
    assert "lat" in pos


def test_disarm_stops_motion(sim):
    sim.armed = True
    sim.target_speed = 1.5
    msg = SimpleNamespace(
        command=mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        param1=0,
    )
    sim.handle_command_long(msg)
    assert sim.armed is False
    assert sim.target_speed == 0.0
