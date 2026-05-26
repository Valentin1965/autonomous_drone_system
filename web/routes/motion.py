from flask import Blueprint, jsonify, request

from web.fleet import get_fleet, resolve_vehicle_id
from web.session_log import record
from web.state import drone_state, logger

motion_bp = Blueprint("motion", __name__)


def _manual_vehicle():
    fleet = get_fleet()
    data = request.get_json(silent=True) or {}
    vid = resolve_vehicle_id(request, data)
    if vid != fleet.selected_id:
        raise PermissionError("manual only for selected vehicle")
    v = fleet.get_vehicle(vid)
    if v.control_mode != "manual":
        raise ValueError("not_manual_mode")
    return v


@motion_bp.route("/api/arm", methods=["POST"])
def api_arm():
    try:
        fleet = get_fleet()
        v = fleet.selected
        v.get_controller().arm()
        record("arm", v.id)
        return jsonify({"status": "ok", "armed": True, "vehicle_id": v.id})
    except Exception as e:
        logger.error(f"arm failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/disarm", methods=["POST"])
def api_disarm():
    try:
        fleet = get_fleet()
        v = fleet.selected
        v.mission_runner.stop()
        v.get_controller().disarm()
        record("disarm", v.id)
        return jsonify({"status": "ok", "armed": False, "vehicle_id": v.id})
    except Exception as e:
        logger.error(f"disarm failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/move", methods=["POST"])
def api_move():
    if drone_state.emergency_stop:
        return jsonify({"status": "blocked", "reason": "emergency_stop"}), 423

    try:
        v = _manual_vehicle()
    except PermissionError:
        return jsonify({
            "status": "ignored",
            "reason": "not_selected",
            "message": "Ручне керування — лише для обраного дрона",
        }), 409
    except ValueError:
        return jsonify({
            "status": "ignored",
            "reason": "not_manual_mode",
            "message": "Увімкніть «Ручний» для обраного дрона",
        }), 409

    if v.mission_runner.active:
        v.mission_runner.pause()

    data = request.get_json(silent=True) or {}
    forward = float(data.get("forward", 0))
    lateral = float(data.get("lateral", 0))
    yaw = float(data.get("yaw", 0))

    try:
        from simulator import fleet_registry

        frame = drone_state.load_config().get("vehicle", {}).get("default_frame", "body")
        ctrl = v.get_controller()
        frame = ctrl.frame or frame

        if fleet_registry.get_sim(v.id) is None:
            ctrl.ensure_connected()
            ctrl.arm()
            ctrl.set_velocity(forward, lateral, yaw)
            return jsonify({
                "status": "ok",
                "vehicle_id": v.id,
                "forward": forward,
                "lateral": lateral,
                "yaw": yaw,
                "frame": frame,
                "drive": "mavlink",
            })

        fleet_registry.arm_sim(v.id)
        if not fleet_registry.apply_manual_velocity(forward, lateral, frame, v.id):
            return jsonify({
                "status": "error",
                "message": "Симулятор не готовий",
            }), 503
        ctrl.arm()
        return jsonify({
            "status": "ok",
            "vehicle_id": v.id,
            "forward": forward,
            "lateral": lateral,
            "yaw": yaw,
            "frame": frame,
            "drive": "simulator",
        })
    except Exception as e:
        logger.error(f"move failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/halt", methods=["POST"])
def api_halt():
    try:
        v = _manual_vehicle()
    except (PermissionError, ValueError):
        v = get_fleet().selected
    try:
        from simulator import fleet_registry

        frame = drone_state.load_config().get("vehicle", {}).get("default_frame", "body")
        if fleet_registry.get_sim(v.id) is not None:
            fleet_registry.apply_manual_velocity(0.0, 0.0, frame, v.id)
        else:
            v.get_controller().stop()
        return jsonify({
            "status": "ok",
            "vehicle_id": v.id,
            "mission_preserved": v.mission_runner.active,
        })
    except Exception as e:
        logger.error(f"halt failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/stop", methods=["POST"])
def api_stop():
    try:
        fleet = get_fleet()
        v = fleet.selected
        from simulator import fleet_registry

        v.mission_runner.stop(wait=True)
        fleet_registry.halt_motion(v.id)
        v.get_controller().stop()
        record("stop_all", v.id)
        return jsonify({"status": "ok", "vehicle_id": v.id})
    except Exception as e:
        logger.error(f"stop failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503


@motion_bp.route("/api/set_mode", methods=["POST"])
def api_set_mode():
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "body")
    try:
        v = get_fleet().selected
        v.get_controller().set_frame(mode)
        return jsonify({"status": "ok", "mode": mode, "vehicle_id": v.id})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503
