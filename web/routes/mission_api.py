"""Mission waypoints API — кліки на карті → маршрут rover."""

from flask import Blueprint, jsonify, request

from web.state import drone_state

mission_bp = Blueprint("mission", __name__)


def _waypoints():
    return drone_state.mission_waypoints


@mission_bp.route("/api/mission", methods=["GET"])
def get_mission():
    return jsonify({"waypoints": list(_waypoints())})


@mission_bp.route("/api/mission", methods=["PUT"])
def set_mission():
    data = request.get_json(silent=True) or {}
    wps = data.get("waypoints", [])
    cleaned = []
    for wp in wps:
        if wp.get("lat") is None or wp.get("lon") is None:
            continue
        cleaned.append({"lat": float(wp["lat"]), "lon": float(wp["lon"])})
    drone_state.mission_waypoints = cleaned
    return jsonify({"waypoints": cleaned, "count": len(cleaned)})


@mission_bp.route("/api/mission/waypoint", methods=["POST"])
def add_waypoint():
    data = request.get_json(silent=True) or {}
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400
    wp = {"lat": float(lat), "lon": float(lon)}
    _waypoints().append(wp)
    return jsonify({"waypoint": wp, "index": len(_waypoints()) - 1, "count": len(_waypoints())})


@mission_bp.route("/api/mission/waypoint/<int:idx>", methods=["DELETE"])
def delete_waypoint(idx: int):
    wps = _waypoints()
    if idx < 0 or idx >= len(wps):
        return jsonify({"error": "invalid index"}), 404
    removed = wps.pop(idx)
    return jsonify({"removed": removed, "count": len(wps)})


@mission_bp.route("/api/mission/clear", methods=["POST"])
def clear_mission():
    drone_state.mission_waypoints = []
    return jsonify({"status": "cleared", "count": 0})


@mission_bp.route("/api/mission/goto", methods=["POST"])
def goto_waypoint():
    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    speed = float(data.get("speed", 1.0))
    wps = _waypoints()

    if idx is not None:
        if idx < 0 or idx >= len(wps):
            return jsonify({"error": "invalid index"}), 404
        wp = wps[int(idx)]
    elif data.get("lat") is not None and data.get("lon") is not None:
        wp = {"lat": float(data["lat"]), "lon": float(data["lon"])}
    else:
        return jsonify({"error": "index or lat/lon required"}), 400

    try:
        ctrl = drone_state.get_controller()
        ctrl.arm()
        ctrl.goto_latlon(wp["lat"], wp["lon"], speed_m_s=speed)
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    return jsonify({"status": "goto", "waypoint": wp, "speed": speed})


@mission_bp.route("/api/mission/run", methods=["POST"])
def run_mission():
    """Послідовно: перша точка (решта — пізніше автопілотом)."""
    wps = _waypoints()
    if not wps:
        return jsonify({"error": "empty mission"}), 400
    speed = float((request.get_json(silent=True) or {}).get("speed", 1.0))
    try:
        ctrl = drone_state.get_controller()
        ctrl.arm()
        ctrl.goto_latlon(wps[0]["lat"], wps[0]["lon"], speed_m_s=speed)
    except Exception as e:
        return jsonify({"error": str(e)}), 503
    return jsonify({"status": "running", "target_index": 0, "total": len(wps)})
