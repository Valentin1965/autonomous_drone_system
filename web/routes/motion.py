from flask import Blueprint, jsonify, request

from web.state import drone_state, logger

motion_bp = Blueprint("motion", __name__)


@motion_bp.route("/api/arm", methods=["POST"])
def api_arm():
    try:
        drone_state.get_controller().arm()
        return jsonify({"status": "ok", "armed": True})
    except Exception as e:
        logger.error(f"arm failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/disarm", methods=["POST"])
def api_disarm():
    try:
        drone_state.get_controller().disarm()
        return jsonify({"status": "ok", "armed": False})
    except Exception as e:
        logger.error(f"disarm failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/move", methods=["POST"])
def api_move():
    if drone_state.emergency_stop:
        return jsonify({"status": "blocked", "reason": "emergency_stop"}), 423

    data = request.get_json(silent=True) or {}
    forward = float(data.get("forward", 0))
    lateral = float(data.get("lateral", 0))
    yaw = float(data.get("yaw", 0))

    try:
        ctrl = drone_state.get_controller()
        ctrl.set_velocity(forward, lateral, yaw)
        return jsonify({
            "status": "ok",
            "forward": forward,
            "lateral": lateral,
            "yaw": yaw,
            "frame": ctrl.frame,
        })
    except Exception as e:
        logger.error(f"move failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/stop", methods=["POST"])
def api_stop():
    try:
        drone_state.get_controller().stop()
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"stop failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/set_mode", methods=["POST"])
def api_set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "body")
    try:
        drone_state.get_controller().set_frame(mode)
        return jsonify({"status": "ok", "mode": mode})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503
