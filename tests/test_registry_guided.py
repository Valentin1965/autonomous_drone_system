"""In-process guided target — рух без UDP."""

import time

from simulator.pixhawk_simulator import PixhawkGPSSimulator
from simulator.registry import get_position, register, set_guided_target, snap_to


def test_set_guided_target_moves_rover():
    sim = PixhawkGPSSimulator("udpin:127.0.0.1:0")
    register(sim)
    snap_to(50.45, 30.52)
    set_guided_target(50.451, 30.525, speed_m_s=2.0)

    lon0 = sim.lon
    for _ in range(30):
        sim.update_position(dt=0.2)
        time.sleep(0.01)

    assert sim.lon != lon0 or sim.lat != 50.45
    pos = get_position()
    assert pos is not None
    assert abs(pos["lon"] - 30.52) > 1e-6
    sim.running = False
