"""GroundController.goto_latlon — MAVLink message must include all fields."""

import socket
import threading
import time

import pytest
from pymavlink import mavutil

from mavlink.ground_controller import GroundController
from simulator.pixhawk_simulator import PixhawkGPSSimulator


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_goto_latlon_does_not_raise():
    port = _free_udp_port()
    sim = PixhawkGPSSimulator(f"udpin:127.0.0.1:{port}")
    sim.running = True
    threading.Thread(target=sim.simulate_movement, daemon=True).start()
    time.sleep(0.4)

    ctrl = GroundController(f"udp:127.0.0.1:{port}")
    ctrl.goto_latlon(50.4502, 30.5240, speed_m_s=1.0)

    sim.running = False
