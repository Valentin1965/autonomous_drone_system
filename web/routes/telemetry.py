from flask import Blueprint, jsonify

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


@telemetry_bp.route("/api/status", methods=["GET"])
def api_status():
    try:
        import time

        from web.tracker_service import is_running

        status = drone_state.get_controller().get_status()
        gps = dict(status.get("gps") or {})
        if not _gps_valid(gps):
            from simulator.registry import get_position

            sim_gps = get_position()
            if sim_gps:
                gps = sim_gps
                status["gps"] = gps
                status["gps_source"] = "simulator"
        else:
            status["gps_source"] = "mavlink"
        status["gps"] = gps
        status["sprayer_active"] = drone_state.sprayer_active
        status["emergency_stop"] = drone_state.emergency_stop
        status["cv_running"] = is_running()
        status["vehicle_type"] = "ground_rover"
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
