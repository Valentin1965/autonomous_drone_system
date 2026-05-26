"""API флоту — вибір дрона, статус усіх."""

from flask import Blueprint, jsonify, request

from web.fleet import get_fleet, resolve_vehicle_id
from web.session_log import record

fleet_bp = Blueprint("fleet", __name__)


@fleet_bp.route("/api/fleet", methods=["GET"])
def api_fleet_list():
    return jsonify(get_fleet().fleet_payload())


@fleet_bp.route("/api/fleet/select", methods=["POST"])
def api_fleet_select():
    data = request.get_json(silent=True) or {}
    vid = data.get("vehicle_id") or data.get("id")
    if not vid:
        return jsonify({"error": "vehicle_id required"}), 400
    try:
        v = get_fleet().select(str(vid))
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    record("fleet_select", v.id)
    return jsonify({
        "status": "ok",
        "selected_vehicle_id": v.id,
        "name": v.name,
        "control_mode": v.control_mode,
        "mission": v.mission_runner.status(),
        "waypoints": list(v.mission_waypoints),
        "record": v.mission_record,
    })


@fleet_bp.route("/api/fleet/configure", methods=["POST"])
def api_fleet_configure():
    data = request.get_json(silent=True) or {}
    count = data.get("count")
    if count is None:
        return jsonify({"error": "count required"}), 400
    try:
        n = int(count)
    except (TypeError, ValueError):
        return jsonify({"error": "count must be integer"}), 400
    try:
        payload = get_fleet().configure_fleet_count(n)
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    record("fleet_configure", str(n))
    return jsonify(payload)


@fleet_bp.route("/api/fleet/warmup", methods=["POST"])
def api_fleet_warmup():
    """Підключити MAVLink до всіх дронів флоту."""
    results = get_fleet().warmup_connections()
    return jsonify({"status": "ok", "links": results})


@fleet_bp.route("/api/fleet/mission/run", methods=["POST"])
def api_fleet_mission_run():
    """Запустити маршрут конкретного дрона (паралельно з іншими)."""
    from web.routes.mission_api import execute_mission_run

    data = request.get_json(silent=True) or {}
    vid = data.get("vehicle_id") or data.get("id")
    if not vid:
        return jsonify({"error": "vehicle_id required"}), 400
    try:
        v = get_fleet().get_vehicle(str(vid))
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    payload, code = execute_mission_run(v, data)
    return jsonify(payload), code
