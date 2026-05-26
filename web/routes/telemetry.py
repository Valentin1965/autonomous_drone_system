import time

from flask import Blueprint, jsonify

from web.app_meta import APP_VERSION, uptime_s
from web.state import drone_state, logger

telemetry_bp = Blueprint("telemetry", __name__)


def _gps_valid(gps: dict) -> bool:
    if not gps:
        return False
    lat = gps.get("lat")
    lon = gps.get("lon")
    if lat is None or lon is None:
        return False
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return abs(lat) > 1e-4 or abs(lon) > 1e-4


def _mavlink_extras(status: dict) -> dict:
    from mavlink.runtime_config import client_connection_string, mavlink_profile
    from simulator.registry import get_sim

    cfg = drone_state.load_config()
    profile = mavlink_profile(cfg)
    sim = get_sim() is not None
    out = {
        "mavlink_profile": profile,
        "mavlink_connection": client_connection_string(cfg, profile),
        "simulator_active": sim,
        "heartbeat_age_s": status.get("heartbeat_age_s"),
        "mavlink_reconnecting": status.get("reconnecting", False),
    }
    warnings = []
    if profile == "px4" and sim:
        warnings.append(
            "Профіль px4, але працює симулятор. Для поля: без --full, MAVLINK_PROFILE=px4."
        )
    if profile == "sim" and not sim and not status.get("connected"):
        warnings.append(
            "Профіль sim, симулятор не запущено. python main.py --full або окремий --simulator."
        )
    if out.get("heartbeat_age_s") is not None and out["heartbeat_age_s"] > 5:
        warnings.append(f"Heartbeat застарів ({out['heartbeat_age_s']} с)")
    if out.get("mavlink_reconnecting"):
        warnings.append("Перепідключення MAVLink…")
    out["warnings"] = warnings
    return out


@telemetry_bp.route("/api/status", methods=["GET"])
def api_status():
    try:
        from web.tracker_service import is_running

        from web.fleet import get_fleet

        fleet = get_fleet()
        v = fleet.selected
        status = v.get_controller().get_status()
        gps = dict(status.get("gps") or {})
        from simulator import fleet_registry

        sim_gps = fleet_registry.get_position(v.id)
        if sim_gps:
            gps = dict(sim_gps)
            status["gps_source"] = "simulator"
            if sim_gps.get("battery_pct") is not None:
                status["battery_pct"] = sim_gps["battery_pct"]
        elif _gps_valid(gps):
            status["gps_source"] = "mavlink"
        status["gps"] = gps
        status["sprayer_active"] = drone_state.sprayer_active
        status["emergency_stop"] = drone_state.emergency_stop
        status["cv_running"] = is_running()
        from web.tracker_service import get_cv_status

        status["cv"] = get_cv_status()
        status["vehicle_type"] = "ground_rover"
        status["mission"] = v.mission_runner.status()
        status["control_mode"] = v.control_mode
        status["vehicle_id"] = v.id
        status["vehicle_name"] = v.name
        status["fleet"] = fleet.fleet_payload()
        status.update(_mavlink_extras(status))
        status["app_version"] = APP_VERSION
        status["uptime_s"] = round(uptime_s(), 1)
        status["ts"] = time.time()
        return jsonify(status)
    except Exception as e:
        logger.error(f"status failed: {e}")
        return jsonify({
            "connected": False,
            "error": str(e),
            "sprayer_active": drone_state.sprayer_active,
            "emergency_stop": drone_state.emergency_stop,
        }), 503
