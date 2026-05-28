"""Підготовка дрона перед місією / CV (симулятор: ARM без ручного кроку)."""

from __future__ import annotations


def prepare_for_motion(vehicle) -> None:
    """ARM in-process sim; MAVLink arm якщо є звʼязок."""
    try:
        from simulator import fleet_registry

        if fleet_registry.get_sim(vehicle.id) is None:
            return
        fleet_registry.arm_sim(vehicle.id)
        ctrl = vehicle.get_controller()
        try:
            ctrl.arm()
        except Exception:
            pass
    except Exception:
        pass
