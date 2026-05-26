from flask import Blueprint, jsonify

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
    drone_state.emergency_stop = True
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
    return jsonify({"status": "emergency_stop"})
