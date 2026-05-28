"""In-process simulator — позиція та керування рухом для --full stack."""

import math
import time

_sim = None
_manual_expires = 0.0

from config.geo_defaults import DEFAULT_LAT as DEFAULT_SIM_LAT
from config.geo_defaults import DEFAULT_LON as DEFAULT_SIM_LON


def register(sim) -> None:
    global _sim
    _sim = sim
    try:
        from simulator import fleet_registry
        from web.fleet import get_fleet

        fleet = get_fleet()
        vid = fleet.selected_id or next(iter(fleet.vehicles), None)
        if vid:
            fleet_registry.register_vehicle(vid, sim)
            fleet_registry.set_active(vid)
    except Exception:
        pass


def unregister() -> None:
    global _sim, _manual_expires
    _sim = None
    _manual_expires = 0.0


def get_sim():
    return _sim


def get_position():
    if _sim is None:
        return None
    return _sim.get_position()


def halt_motion() -> None:
    """Повна зупинка (кнопка Стоп / кінець маршруту)."""
    if _sim is None:
        return
    with _sim.lock:
        _sim.target_speed = 0.0
        _sim.speed = 0.0
        _sim.guided_active = False
        _sim.target_lat = None
        _sim.target_lon = None


def is_default_sim_position(pos) -> bool:
    if not pos:
        return True
    try:
        lat, lon = float(pos["lat"]), float(pos["lon"])
    except (TypeError, ValueError, KeyError):
        return True
    return (
        abs(lat - DEFAULT_SIM_LAT) < 2e-4
        and abs(lon - DEFAULT_SIM_LON) < 2e-4
    )


def snap_to(lat: float, lon: float) -> None:
    """Поставити rover на waypoint (старт маршруту з точки 1)."""
    if _sim is None:
        return
    with _sim.lock:
        _sim.lat = float(lat)
        _sim.lon = float(lon)
        _sim.speed = 0.0
        _sim.target_speed = 0.0
        _sim.guided_active = False
        _sim.target_lat = None
        _sim.target_lon = None


def snap_to_start_waypoint_if_needed(waypoints) -> bool:
    """Поставити симулятор на точку 1, якщо ще не там."""
    from simulator.fleet_registry import snap_to_start_waypoint_if_needed as fleet_snap

    return fleet_snap(waypoints, None)


def arm_sim() -> bool:
    """ARM у in-process симуляторі (--full)."""
    if _sim is None:
        return False
    with _sim.lock:
        _sim.armed = True
        _sim.mode = "GUIDED"
    return True


def apply_manual_velocity(
    forward: float, lateral: float, frame: str = "body"
) -> bool:
    """Ручний рух (dpad) — без UDP, лише velocity setpoint."""
    global _manual_expires
    if _sim is None:
        return False
    forward = float(forward)
    lateral = float(lateral)
    speed = math.hypot(forward, lateral)
    with _sim.lock:
        if speed < 0.02:
            _sim.target_speed = 0.0
            _sim.speed = 0.0
            _sim.target_lat = None
            _sim.target_lon = None
            _sim.guided_active = False
            _manual_expires = 0.0
            return True
        if frame == "body":
            hr = math.radians(_sim.heading)
            vn = forward * math.cos(hr) - lateral * math.sin(hr)
            ve = forward * math.sin(hr) + lateral * math.cos(hr)
            _sim.target_heading = math.degrees(math.atan2(ve, vn)) % 360
        else:
            _sim.target_heading = math.degrees(math.atan2(lateral, forward)) % 360
        _sim.target_speed = min(2.5, max(0.05, speed))
        _sim.target_lat = None
        _sim.target_lon = None
        _sim.guided_active = True
        _sim.armed = True
        _sim.mode = "GUIDED"
        if _sim.speed < 0.05:
            _sim.speed = min(_sim.target_speed, 0.2)
    _manual_expires = time.monotonic() + 0.45
    return True


def manual_drive_active() -> bool:
    return _sim is not None and time.monotonic() < _manual_expires


def set_guided_target(lat: float, lon: float, speed_m_s: float = 1.0) -> bool:
    """Ціль для руху — без залежності від UDP (GCS + симулятор в одному процесі)."""
    if _sim is None:
        return False
    with _sim.lock:
        _sim.target_lat = float(lat)
        _sim.target_lon = float(lon)
        _sim.target_speed = max(0.1, float(speed_m_s))
        _sim.guided_active = True
        _sim.armed = True
        _sim.mode = "GUIDED"
    return True
