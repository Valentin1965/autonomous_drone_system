"""Перевірки перед рухом / стартом місії та CV."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from web import geofence


def gps_valid(gps: Optional[dict]) -> bool:
    if not gps:
        return False
    try:
        lat = float(gps.get("lat"))
        lon = float(gps.get("lon"))
    except (TypeError, ValueError):
        return False
    return abs(lat) > 1e-4 or abs(lon) > 1e-4


def _sim_active(vehicle_id: str) -> bool:
    try:
        from simulator import fleet_registry

        return fleet_registry.get_sim(vehicle_id) is not None
    except Exception:
        return False


def _vehicle_gps(vehicle, mavlink_status: dict) -> dict:
    gps = dict(mavlink_status.get("gps") or {})
    try:
        from simulator import fleet_registry

        sim_gps = fleet_registry.get_position(vehicle.id)
        if sim_gps:
            return dict(sim_gps)
    except Exception:
        pass
    return gps


def evaluate(
    vehicle,
    *,
    mavlink_status: Optional[dict] = None,
    require_route: bool = False,
    require_arm: bool = True,
) -> Dict[str, Any]:
    from web.fleet import get_fleet

    fleet = get_fleet()
    try:
        st = mavlink_status or vehicle.get_controller().get_status()
    except Exception:
        st = {"connected": False, "armed": False, "gps": {}}

    gps = _vehicle_gps(vehicle, st)
    wps = list(vehicle.mission_waypoints or [])
    sim_dev = _sim_active(vehicle.id)

    fence_on = geofence.is_enabled()
    geo_ok = True
    geo_detail = ""
    if fence_on:
        geo_ok = True
        if gps_valid(gps):
            geo_ok, geo_detail = geofence.check_position(
                float(gps["lat"]), float(gps["lon"])
            )
        route_ok, route_msg = geofence.check_waypoints(wps)
        if not route_ok:
            geo_ok = False
            geo_detail = route_msg or geo_detail

    mavlink_ok = bool(st.get("connected")) and not bool(st.get("reconnecting"))
    if sim_dev and gps_valid(gps):
        mavlink_ok = True
    armed_ok = bool(st.get("armed")) or sim_dev

    checks = {
        "mavlink": {
            "ok": mavlink_ok,
            "label": "MAVLink підключено" if not sim_dev else "Симулятор / MAVLink",
        },
        "gps": {
            "ok": gps_valid(gps),
            "label": "GPS / позиція валідна",
        },
        "armed": {
            "ok": armed_ok,
            "label": "ARM (двигуни дозволено)" if not sim_dev else "ARM (авто при старті в sim)",
        },
        "emergency_clear": {
            "ok": not fleet.emergency_stop,
            "label": "Немає аварійної зупинки",
        },
        "geofence": {
            "ok": geo_ok,
            "label": (
                "Геозона: дрон і маршрут всередині"
                if fence_on
                else "Геозона (опційно — «2 кути» або «За маршрутом»)"
            ),
            "detail": geo_detail,
            "optional": not fence_on,
        },
        "route": {
            "ok": len(wps) > 0,
            "label": "Маршрут: ≥1 точка",
            "optional": True,
        },
    }

    required_mission = ["mavlink", "gps", "armed", "emergency_clear"]
    if fence_on:
        required_mission.append("geofence")
    if require_route:
        required_mission.append("route")

    required_cv = ["mavlink", "gps", "armed", "emergency_clear"]
    if fence_on:
        required_cv.append("geofence")

    def _ready(keys: List[str]) -> bool:
        return all(checks[k]["ok"] for k in keys)

    ready_mission = _ready(required_mission)
    ready_cv = _ready(required_cv)

    block_reason = ""
    if not ready_mission:
        failed = [checks[k]["label"] for k in required_mission if not checks[k]["ok"]]
        block_reason = "Не готово до старту: " + "; ".join(failed)

    return {
        "ready_for_mission": ready_mission,
        "ready_for_cv": ready_cv,
        "checks": checks,
        "block_reason": block_reason,
        "require_arm": require_arm,
    }


def assert_ready_for_mission(vehicle, mavlink_status: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    pf = evaluate(vehicle, mavlink_status=mavlink_status, require_route=True, require_arm=True)
    if pf["ready_for_mission"]:
        return None
    return {
        "error": "preflight_failed",
        "message": pf["block_reason"],
        "preflight": pf,
    }


def assert_ready_for_cv(vehicle, mavlink_status: Optional[dict] = None) -> Optional[Dict[str, Any]]:
    pf = evaluate(vehicle, mavlink_status=mavlink_status, require_route=False, require_arm=True)
    if pf["ready_for_cv"]:
        return None
    return {
        "error": "preflight_failed",
        "message": pf["block_reason"],
        "preflight": pf,
    }
