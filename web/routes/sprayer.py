from flask import Blueprint, jsonify, request

from web.session_log import record
from web.state import drone_state, logger

sprayer_bp = Blueprint("sprayer", __name__)


def _set_sprayer(on: bool, *, source: str = "manual"):
    from web.fleet import get_fleet

    fleet = get_fleet()
    drone_state.sprayer_active = on
    v = fleet.selected
    if v:
        v.sprayer_active = on
    metrics = None
    try:
        from monitoring.spray_coverage import on_sprayer_transition

        if v:
            metrics = on_sprayer_transition(v, on, source=source, uplink=True)
    except Exception:
        pass
    return v, metrics


@sprayer_bp.route("/api/sprayer/on", methods=["POST"])
def api_sprayer_on():
    logger.info("Оприскувач УВІМКНЕНО")
    record("sprayer_on")
    _set_sprayer(True, source="manual")
    return jsonify({"sprayer": "on"})


@sprayer_bp.route("/api/sprayer/off", methods=["POST"])
def api_sprayer_off():
    logger.info("Оприскувач ВИМКНЕНО")
    record("sprayer_off")
    _v, metrics = _set_sprayer(False, source="manual")
    out = {"sprayer": "off"}
    if metrics:
        out["spray_coverage"] = metrics
    return jsonify(out)


@sprayer_bp.route("/api/sprayer/coverage", methods=["GET"])
def api_sprayer_coverage():
    """Локальна статистика обробленої ділянки (GPS + час spray)."""
    from web.fleet import get_fleet, resolve_vehicle_id

    from monitoring.spray_coverage import vehicle_summary

    v = get_fleet().get_vehicle(resolve_vehicle_id(request))
    if not v:
        return jsonify({"error": "vehicle not found"}), 404
    return jsonify({"status": "ok", "coverage": vehicle_summary(v.id)})


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
        if v.sprayer_active:
            try:
                from monitoring.spray_coverage import on_sprayer_transition

                v.sprayer_active = False
                on_sprayer_transition(v, False, source="emergency", uplink=True)
            except Exception:
                v.sprayer_active = False
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
    drone_state.sprayer_active = False
    logger.critical("АВАРІЙНА ЗУПИНКА АКТИВОВАНА!")
    record("emergency_stop", level="error")
    return jsonify({"status": "emergency_stop", "emergency_stop": True})


@sprayer_bp.route("/api/emergency/reset", methods=["POST"])
def api_emergency_reset():
    """Скинути прапорець аварійної зупинки (після перевірки оператором)."""
    from web.fleet import get_fleet

    fleet = get_fleet()
    fleet.emergency_stop = False
    logger.info("Аварійну зупинку скинуто оператором")
    record("emergency_reset")
    return jsonify({"status": "ok", "emergency_stop": False})
