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

@fleet_bp.route("/api/fleet/active/set", methods=["POST"])
def api_fleet_active_set():
    """Задати список активних дронів (пул 6)."""
    data = request.get_json(silent=True) or {}
    ids = data.get("active_vehicle_ids") or data.get("active_ids") or data.get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "active_vehicle_ids must be list"}), 400
    try:
        payload = get_fleet().configure_fleet_active([str(x) for x in ids])
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    record("fleet_active_set", ",".join(payload.get("active_vehicle_ids") or []))
    return jsonify(payload)


@fleet_bp.route("/api/fleet/active/toggle", methods=["POST"])
def api_fleet_active_toggle():
    """Увімкнути/вимкнути один дрон у пулі."""
    data = request.get_json(silent=True) or {}
    vid = data.get("vehicle_id") or data.get("id")
    active = data.get("active")
    if not vid:
        return jsonify({"error": "vehicle_id required"}), 400
    if active is None:
        return jsonify({"error": "active required"}), 400
    try:
        payload = get_fleet().set_vehicle_active(str(vid), bool(active))
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    record("fleet_active_toggle", f"{vid}:{int(bool(active))}")
    return jsonify(payload)


@fleet_bp.route("/api/fleet/warmup", methods=["POST"])
def api_fleet_warmup():
    """Підключити MAVLink до всіх дронів флоту."""
    results = get_fleet().warmup_connections()
    return jsonify({"status": "ok", "links": results})


@fleet_bp.route("/api/fleet/cv/connect", methods=["POST"])
def api_fleet_cv_connect():
    """Підключити відео/камеру для дрона (dev: .mp4 з video_file, поле: потік з борту)."""
    from web.tracker_service import connect_cv

    data = request.get_json(silent=True) or {}
    vid = data.get("vehicle_id") or data.get("id")
    if not vid:
        return jsonify({"error": "vehicle_id required"}), 400
    try:
        payload = connect_cv(str(vid), select_vehicle=True)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    code = 503 if payload.get("status") == "error" else 200
    record("fleet_cv_connect", f"{vid}:{payload.get('status')}")
    return jsonify(payload), code


@fleet_bp.route("/api/fleet/cv/disconnect", methods=["POST"])
def api_fleet_cv_disconnect():
    from web.tracker_service import disconnect_cv

    data = request.get_json(silent=True) or {}
    vid = data.get("vehicle_id") or data.get("id")
    payload = disconnect_cv(str(vid) if vid else None)
    record("fleet_cv_disconnect", str(vid or "all"))
    return jsonify(payload)


@fleet_bp.route("/api/fleet/cv/videos", methods=["GET"])
def api_fleet_cv_videos():
    """Список відеофайлів у assets/videos (на диску, не в git)."""
    from web.fleet_video import list_assets_videos, videos_directory

    files = list_assets_videos()
    return jsonify({
        "video_dir": str(videos_directory()),
        "count": len(files),
        "files": [
            {"name": p.name, "path": str(p), "size_bytes": p.stat().st_size}
            for p in files
        ],
    })


@fleet_bp.route("/api/fleet/cv/status", methods=["GET"])
def api_fleet_cv_status():
    from web.tracker_service import fleet_cv_status

    vid = request.args.get("vehicle_id") or request.args.get("vehicle")
    if vid:
        try:
            return jsonify(fleet_cv_status(str(vid)))
        except KeyError as e:
            return jsonify({"error": str(e)}), 404
    fleet = get_fleet()
    return jsonify({
        "vehicles": [fleet_cv_status(v.id) for v in fleet.vehicles.values()],
    })


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
