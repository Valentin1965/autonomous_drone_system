from flask import Blueprint, jsonify

from web.session_log import record
from web.state import drone_state, logger
from web.tracker_service import get_tracker

sprayer_bp = Blueprint("sprayer", __name__)


@sprayer_bp.route("/api/sprayer/on", methods=["POST"])
def api_sprayer_on():
    drone_state.sprayer_active = True
    logger.info("Оприскувач УВІМКНЕНО")
    return jsonify({"sprayer": "on"})


@sprayer_bp.route("/api/sprayer/off", methods=["POST"])
def api_sprayer_off():
    drone_state.sprayer_active = False
    logger.info("Оприскувач ВИМКНЕНО")
    return jsonify({"sprayer": "off"})


@sprayer_bp.route("/api/emergency/stop", methods=["POST"])
def api_emergency_stop():
    from simulator import fleet_registry
    from web.fleet import get_fleet

    fleet = get_fleet()
    fleet.emergency_stop = True
    for v in fleet.vehicles.values():
        v.mission_runner.stop()
        try:
            v.get_controller().stop()
        except Exception:
            pass
    fleet_registry.halt_all()
    try:
        drone_state.get_controller().stop()
    except Exception:
        pass
    try:
        from web.motion_bridge import MotionBridge
        MotionBridge().stop()
    except Exception:
        pass
    logger.critical("АВАРІЙНА ЗУПИНКА АКТИВОВАНА!")
    record("emergency_stop", level="error")
    return jsonify({"status": "emergency_stop"})
