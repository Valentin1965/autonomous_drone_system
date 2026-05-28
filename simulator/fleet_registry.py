"""In-process симулятори — по одному на кожен vehicle_id."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional

_sims: Dict[str, Any] = {}
_active_id: Optional[str] = None
_manual_expires: Dict[str, float] = {}

from config.geo_defaults import DEFAULT_LAT as DEFAULT_SIM_LAT
from config.geo_defaults import DEFAULT_LON as DEFAULT_SIM_LON


def register_vehicle(vehicle_id: str, sim: Any) -> None:
    _sims[str(vehicle_id)] = sim


def unregister_vehicle(vehicle_id: str) -> None:
    global _active_id
    vid = str(vehicle_id)
    sim = _sims.pop(vid, None)
    _manual_expires.pop(vid, None)
    if sim is not None:
        try:
            sim.stop()
        except Exception:
            pass
    if _active_id == vid:
        _active_id = next(iter(_sims), None)


def unregister_all() -> None:
    global _active_id, _manual_expires
    for vid in list(_sims.keys()):
        unregister_vehicle(vid)
    _manual_expires.clear()
    _active_id = None


def set_active(vehicle_id: str) -> None:
    global _active_id
    vid = str(vehicle_id)
    if vid not in _sims:
        raise KeyError(f"unknown vehicle {vid}")
    _active_id = vid


def get_active_id() -> Optional[str]:
    return _active_id


def get_sim(vehicle_id: Optional[str] = None) -> Any:
    vid = vehicle_id or _active_id
    if vid is None and len(_sims) == 1:
        vid = next(iter(_sims))
    if vid is None:
        return None
    return _sims.get(str(vid))


def list_vehicle_ids() -> list:
    return list(_sims.keys())


def get_position(vehicle_id: Optional[str] = None) -> Optional[dict]:
    sim = get_sim(vehicle_id)
    if sim is None:
        return None
    return sim.get_position()


def halt_motion(vehicle_id: Optional[str] = None) -> None:
    sim = get_sim(vehicle_id)
    if sim is None:
        return
    with sim.lock:
        sim.target_speed = 0.0
        sim.speed = 0.0
        sim.guided_active = False
        sim.target_lat = None
        sim.target_lon = None


def halt_all() -> None:
    for vid in list(_sims.keys()):
        halt_motion(vid)


def _mission_blocks_snap(vehicle_id: Optional[str]) -> bool:
    """Не телепортувати / скидати guided під час місії (паралельний флот)."""
    if not vehicle_id:
        return False
    try:
        from web.fleet import get_fleet

        phase = (
            get_fleet()
            .get_vehicle(str(vehicle_id))
            .mission_runner.status()
            .get("phase", "idle")
        )
        return phase in ("running", "returning", "paused")
    except Exception:
        return False


def snap_to(lat: float, lon: float, vehicle_id: Optional[str] = None) -> None:
    if _mission_blocks_snap(vehicle_id):
        return
    sim = get_sim(vehicle_id)
    if sim is None:
        return
    with sim.lock:
        sim.lat = float(lat)
        sim.lon = float(lon)
        sim.speed = 0.0
        sim.target_speed = 0.0
        sim.guided_active = False
        sim.target_lat = None
        sim.target_lon = None


def is_default_sim_position(pos, vehicle_id: Optional[str] = None) -> bool:
    sim = get_sim(vehicle_id)
    if sim is None:
        return True
    try:
        lat, lon = float(pos["lat"]), float(pos["lon"])
    except (TypeError, ValueError, KeyError):
        return True
    with sim.lock:
        dlat = abs(lat - sim.lat) < 2e-4
        dlon = abs(lon - sim.lon) < 2e-4
    return dlat and dlon


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6378137.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def snap_to_start_waypoint_if_needed(waypoints, vehicle_id: Optional[str] = None) -> bool:
    """Поставити симулятор на точку 1 маршруту (не на центр карти)."""
    if _mission_blocks_snap(vehicle_id):
        return False
    if not waypoints:
        return False
    wp0 = waypoints[0]
    tlat = float(wp0["lat"])
    tlon = float(wp0["lon"])
    pos = get_position(vehicle_id)
    if pos:
        try:
            dist = _haversine_m(
                float(pos["lat"]),
                float(pos["lon"]),
                tlat,
                tlon,
            )
            if dist < 2.5:
                return False
        except (TypeError, ValueError):
            pass
    snap_to(tlat, tlon, vehicle_id)
    return True


def arm_sim(vehicle_id: Optional[str] = None) -> bool:
    sim = get_sim(vehicle_id)
    if sim is None:
        return False
    with sim.lock:
        sim.armed = True
        sim.mode = "GUIDED"
    return True


def apply_manual_velocity(
    forward: float,
    lateral: float,
    frame: str = "body",
    vehicle_id: Optional[str] = None,
) -> bool:
    vid = vehicle_id or _active_id
    sim = get_sim(vid)
    if sim is None:
        return False
    forward = float(forward)
    lateral = float(lateral)
    speed = math.hypot(forward, lateral)
    with sim.lock:
        if speed < 0.02:
            sim.target_speed = 0.0
            sim.speed = 0.0
            sim.target_lat = None
            sim.target_lon = None
            sim.guided_active = False
            if vid:
                _manual_expires[vid] = 0.0
            return True
        if frame == "body":
            hr = math.radians(sim.heading)
            vn = forward * math.cos(hr) - lateral * math.sin(hr)
            ve = forward * math.sin(hr) + lateral * math.cos(hr)
            sim.target_heading = math.degrees(math.atan2(ve, vn)) % 360
        else:
            sim.target_heading = math.degrees(math.atan2(lateral, forward)) % 360
        sim.target_speed = min(2.5, max(0.05, speed))
        sim.target_lat = None
        sim.target_lon = None
        sim.guided_active = True
        sim.armed = True
        sim.mode = "GUIDED"
        if sim.speed < 0.05:
            sim.speed = min(sim.target_speed, 0.2)
    if vid:
        _manual_expires[vid] = time.monotonic() + 0.45
    return True


def manual_drive_active(vehicle_id: Optional[str] = None) -> bool:
    vid = vehicle_id or _active_id
    if not vid:
        return False
    return time.monotonic() < _manual_expires.get(vid, 0.0)


def set_guided_target(
    lat: float,
    lon: float,
    speed_m_s: float = 1.0,
    vehicle_id: Optional[str] = None,
) -> bool:
    sim = get_sim(vehicle_id)
    if sim is None:
        return False
    with sim.lock:
        sim.target_lat = float(lat)
        sim.target_lon = float(lon)
        sim.target_speed = max(0.1, float(speed_m_s))
        sim.guided_active = True
        sim.armed = True
        sim.mode = "GUIDED"
    return True
