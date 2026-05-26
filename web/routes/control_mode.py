"""Перемикання автономний / ручний — лише для обраного дрона."""

from flask import Blueprint, jsonify, request

from web.fleet import get_fleet, resolve_vehicle_id
from web.session_log import record

control_bp = Blueprint("control", __name__)


def _selected_vehicle():
    fleet = get_fleet()
    data = request.get_json(silent=True) or {}
    vid = resolve_vehicle_id(request, data)
    if vid != fleet.selected_id:
        raise PermissionError("manual control only for selected vehicle")
    return fleet.get_vehicle(vid)


@control_bp.route("/api/control/mode", methods=["GET"])
def get_control_mode():
    fleet = get_fleet()
    v = fleet.selected
    return jsonify({
        "mode": v.control_mode,
        "vehicle_id": v.id,
        "mission": v.mission_runner.status(),
        "fleet": fleet.fleet_payload(),
    })


@control_bp.route("/api/control/mode/manual", methods=["POST"])
def set_manual_mode():
    try:
        v = _selected_vehicle()
    except PermissionError as e:
        return jsonify({"error": "not_selected", "message": str(e)}), 409
    try:
        if v.mission_runner.active:
            v.mission_runner.pause()
        else:
            from simulator import fleet_registry

            frame = get_fleet().load_config().get("vehicle", {}).get("default_frame", "body")
            fleet_registry.apply_manual_velocity(0.0, 0.0, frame, v.id)
            try:
                v.get_controller().stop()
            except Exception:
                pass
            fleet_registry.halt_motion(v.id)

        from simulator import fleet_registry

        fleet_registry.arm_sim(v.id)
        v.set_control_mode("manual")
        record("manual_mode", v.id)
        return jsonify({
            "mode": "manual",
            "vehicle_id": v.id,
            "mission": v.mission_runner.status(),
            "message": f"Ручний: {v.name} — стрілки керують лише цим дроном",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@control_bp.route("/api/control/mode/autonomous", methods=["POST"])
def set_autonomous_mode():
    """Автономний режим — для будь-якого дрона (vehicle_id у JSON/query)."""
    fleet = get_fleet()
    data = request.get_json(silent=True) or {}
    try:
        vid = resolve_vehicle_id(request, data)
        v = fleet.get_vehicle(vid)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    try:
        ctrl = v.get_controller()
        ctrl.stop()
        from simulator import fleet_registry

        if not v.mission_runner.active:
            fleet_registry.halt_motion(v.id)
        v.set_control_mode("autonomous")
        st = v.mission_runner.status()
        msg = f"Автономний: {v.name}"
        if st.get("can_resume"):
            msg += " — «▶ Старт маршруту»"
        elif st.get("phase") == "idle" and v.mission_waypoints:
            msg += " — «▶ Старт маршруту»"
        record("autonomous_mode", v.id)
        return jsonify({
            "mode": "autonomous",
            "vehicle_id": v.id,
            "mission": st,
            "message": msg,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@control_bp.route("/api/control/mode", methods=["POST"])
def set_control_mode():
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "").strip().lower()
    if mode == "manual":
        return set_manual_mode()
    if mode == "autonomous":
        return set_autonomous_mode()
    return jsonify({"error": "mode must be autonomous or manual"}), 400
