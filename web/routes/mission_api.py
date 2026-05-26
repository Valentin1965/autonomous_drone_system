"""Mission waypoints API — кліки на карті → маршрут rover."""

from flask import Blueprint, jsonify, request

from web.fleet import get_fleet, resolve_vehicle_id
from web.mission_record import (
    export_payload,
    normalize_record,
    record_from_import,
    supported_formats,
)
from web.session_log import record
from web.state import drone_state

mission_bp = Blueprint("mission", __name__)


def _request_data():
    return request.get_json(silent=True) or {}


def _vehicle():
    vid = resolve_vehicle_id(request, _request_data())
    return get_fleet().get_vehicle(vid)


def _clamp_speed(speed, default: float = 1.0) -> float:
    mcfg = drone_state.load_config().get("mission", {})
    lo = float(mcfg.get("min_speed_m_s", 0.3))
    hi = float(mcfg.get("max_speed_m_s", 3.0))
    try:
        v = float(speed)
    except (TypeError, ValueError):
        v = float(mcfg.get("default_speed_m_s", default))
    return max(lo, min(hi, v))


def _waypoints(vehicle=None):
    v = vehicle or _vehicle()
    return v.mission_waypoints


def _route_editable(vehicle=None) -> bool:
    v = vehicle or _vehicle()
    phase = v.mission_runner.status().get("phase", "idle")
    return phase not in ("running", "returning")


def _route_locked_response():
    return jsonify({
        "error": "mission_active",
        "message": "Зупиніть маршрут (■ Стоп), потім редагуйте точки",
    }), 409


def _after_waypoints_changed(vehicle=None) -> None:
    v = vehicle or _vehicle()
    wps = list(_waypoints(v))
    phase = v.mission_runner.status().get("phase", "idle")
    if phase in ("paused", "idle", "aborted", "at_last", "completed"):
        try:
            v.mission_runner.update_route_waypoints(wps)
        except ValueError:
            pass


@mission_bp.route("/api/mission", methods=["GET"])
def get_mission():
    v = _vehicle()
    return jsonify({
        "vehicle_id": v.id,
        "waypoints": list(_waypoints(v)),
        "record": normalize_record(v.mission_record),
    })


@mission_bp.route("/api/mission/record", methods=["GET", "PUT"])
def mission_record_api():
    v = _vehicle()
    if request.method == "GET":
        return jsonify({
            "vehicle_id": v.id,
            "record": normalize_record(v.mission_record),
        })
    data = _request_data()
    rec = data.get("record", data)
    v.mission_record = normalize_record({
        "work_started_at": rec.get("work_started_at"),
        "work_finished_at": rec.get("work_finished_at"),
        "spraying": rec.get("spraying", {}),
        "field_notes": rec.get("field_notes", ""),
    })
    record("mission_record", v.id)
    return jsonify({
        "vehicle_id": v.id,
        "record": normalize_record(v.mission_record),
    })


@mission_bp.route("/api/mission/export", methods=["GET"])
def export_mission():
    v = _vehicle()
    mcfg = drone_state.load_config().get("mission", {})
    speed = float(mcfg.get("default_speed_m_s", 1.0))
    return jsonify(
        export_payload(v.id, list(_waypoints(v)), v.mission_record, speed)
    )


@mission_bp.route("/api/mission/import", methods=["POST"])
def import_mission():
    v = _vehicle()
    if not _route_editable(v):
        return _route_locked_response()
    data = _request_data()
    if not supported_formats(data):
        return jsonify({"error": "unsupported format"}), 400
    wps = data.get("waypoints", [])
    cleaned = []
    for wp in wps:
        if wp.get("lat") is None or wp.get("lon") is None:
            continue
        cleaned.append({"lat": float(wp["lat"]), "lon": float(wp["lon"])})
    v.mission_waypoints = cleaned
    v.mission_record = record_from_import(data)
    _after_waypoints_changed(v)
    record("mission_import", f"{v.id}:{len(cleaned)} wp")
    return jsonify({
        "vehicle_id": v.id,
        "waypoints": cleaned,
        "count": len(cleaned),
        "record": normalize_record(v.mission_record),
    })


@mission_bp.route("/api/mission/sync_start", methods=["POST"])
def sync_start_position():
    """Синхронізувати позицію дрона з точкою 1 маршруту (кожен дрон окремо)."""
    v = _vehicle()
    wps = list(_waypoints(v))
    if not wps:
        return jsonify({"synced": False, "reason": "no_waypoints"})
    from simulator import fleet_registry

    synced = fleet_registry.snap_to_start_waypoint_if_needed(wps, v.id)
    pos = fleet_registry.get_position(v.id)
    out = {"synced": synced, "vehicle_id": v.id, "waypoints": len(wps)}
    if pos:
        out["position"] = {
            "lat": float(pos["lat"]),
            "lon": float(pos["lon"]),
        }
    return jsonify(out)


@mission_bp.route("/api/mission", methods=["PUT"])
def set_mission():
    v = _vehicle()
    data = _request_data()
    wps = data.get("waypoints", [])
    cleaned = []
    for wp in wps:
        if wp.get("lat") is None or wp.get("lon") is None:
            continue
        cleaned.append({"lat": float(wp["lat"]), "lon": float(wp["lon"])})
    if not _route_editable(v):
        return _route_locked_response()
    v.mission_waypoints = cleaned
    _after_waypoints_changed(v)
    record("mission_set", f"{v.id}:{len(cleaned)} wp")
    return jsonify({"vehicle_id": v.id, "waypoints": cleaned, "count": len(cleaned)})


@mission_bp.route("/api/mission/waypoint", methods=["POST"])
def add_waypoint():
    v = _vehicle()
    if not _route_editable(v):
        return _route_locked_response()
    data = _request_data()
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400
    wp = {"lat": float(lat), "lon": float(lon)}
    v.mission_waypoints.append(wp)
    idx = len(v.mission_waypoints) - 1
    if idx == 0:
        from simulator import fleet_registry

        fleet_registry.snap_to(wp["lat"], wp["lon"], v.id)
    _after_waypoints_changed(v)
    return jsonify({
        "vehicle_id": v.id,
        "waypoint": wp,
        "index": idx,
        "count": len(v.mission_waypoints),
    })


@mission_bp.route("/api/mission/waypoint/<int:idx>", methods=["PUT"])
def update_waypoint(idx: int):
    v = _vehicle()
    if not _route_editable(v):
        return _route_locked_response()
    wps = v.mission_waypoints
    if idx < 0 or idx >= len(wps):
        return jsonify({"error": "invalid index"}), 404
    data = _request_data()
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "lat and lon required"}), 400
    wp = {"lat": float(lat), "lon": float(lon)}
    wps[idx] = wp
    if idx == 0:
        from simulator import fleet_registry

        fleet_registry.snap_to(wp["lat"], wp["lon"], v.id)
    _after_waypoints_changed(v)
    return jsonify({"vehicle_id": v.id, "waypoint": wp, "index": idx, "count": len(wps)})


@mission_bp.route("/api/mission/waypoint/<int:idx>", methods=["DELETE"])
def delete_waypoint(idx: int):
    v = _vehicle()
    if not _route_editable(v):
        return _route_locked_response()
    wps = v.mission_waypoints
    if idx < 0 or idx >= len(wps):
        return jsonify({"error": "invalid index"}), 404
    removed = wps.pop(idx)
    _after_waypoints_changed(v)
    return jsonify({"vehicle_id": v.id, "removed": removed, "count": len(wps)})


@mission_bp.route("/api/mission/clear", methods=["POST"])
def clear_mission():
    v = _vehicle()
    v.mission_runner.stop()
    v.mission_waypoints = []
    return jsonify({"vehicle_id": v.id, "status": "cleared", "count": 0})


@mission_bp.route("/api/mission/stop", methods=["POST"])
def stop_mission():
    v = _vehicle()
    from simulator import fleet_registry

    v.mission_runner.stop(wait=True)
    fleet_registry.halt_motion(v.id)
    record("mission_stop", v.id)
    return jsonify({"vehicle_id": v.id, "status": "stopped", **v.mission_runner.status()})


@mission_bp.route("/api/mission/return", methods=["POST"])
def return_mission():
    v = _vehicle()
    if v.control_mode != "autonomous":
        return jsonify({
            "error": "not_autonomous",
            "message": "Увімкніть «Автономний» для цього дрона",
        }), 409
    data = _request_data()
    speed = data.get("speed")
    speed_f = _clamp_speed(speed) if speed is not None else None
    try:
        st = v.mission_runner.start_return(speed_m_s=speed_f)
    except ValueError as e:
        return jsonify({"error": str(e), "status": "error"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 503
    return jsonify({"vehicle_id": v.id, "status": "returning", **st})


@mission_bp.route("/api/mission/status", methods=["GET"])
def mission_status():
    v = _vehicle()
    return jsonify(v.mission_runner.status())


@mission_bp.route("/api/mission/settings", methods=["GET"])
def mission_settings():
    mcfg = drone_state.load_config().get("mission", {})
    presets = mcfg.get("presets") or {}
    return jsonify({
        "default_speed_m_s": float(mcfg.get("default_speed_m_s", 1.0)),
        "min_speed_m_s": float(mcfg.get("min_speed_m_s", 0.3)),
        "max_speed_m_s": float(mcfg.get("max_speed_m_s", 3.0)),
        "presets": {
            "spray_m_s": float(presets.get("spray_m_s", 0.8)),
            "row_m_s": float(presets.get("row_m_s", 1.0)),
            "transfer_m_s": float(presets.get("transfer_m_s", 1.5)),
        },
    })


@mission_bp.route("/api/mission/goto", methods=["POST"])
def goto_waypoint():
    v = _vehicle()
    data = _request_data()
    idx = data.get("index")
    speed = _clamp_speed(data.get("speed", 1.0))
    wps = v.mission_waypoints

    if idx is not None:
        if idx < 0 or idx >= len(wps):
            return jsonify({"error": "invalid index"}), 404
        wp = wps[int(idx)]
    elif data.get("lat") is not None and data.get("lon") is not None:
        wp = {"lat": float(data["lat"]), "lon": float(data["lon"])}
    else:
        return jsonify({"error": "index or lat/lon required"}), 400

    try:
        ctrl = v.get_controller()
        ctrl.arm()
        ctrl.goto_latlon(wp["lat"], wp["lon"], speed_m_s=speed)
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    return jsonify({"vehicle_id": v.id, "status": "goto", "waypoint": wp, "speed": speed})


def execute_mission_run(v, data: dict) -> tuple:
    """Запуск маршруту для vehicle; повертає (payload_dict, http_status)."""
    if data.get("waypoints"):
        cleaned = []
        for wp in data["waypoints"]:
            if wp.get("lat") is None or wp.get("lon") is None:
                continue
            cleaned.append({"lat": float(wp["lat"]), "lon": float(wp["lon"])})
        v.mission_waypoints = cleaned

    if v.control_mode != "autonomous":
        return {
            "error": "not_autonomous",
            "message": f"Дрон {v.name}: увімкніть «Автономний»",
        }, 409

    wps = list(v.mission_waypoints)
    if not wps:
        return {
            "error": "empty mission",
            "message": "Додайте точки на карті для цього дрона",
        }, 400
    speed = _clamp_speed(data.get("speed", 1.0))
    mr = v.mission_runner
    try:
        if mr.status().get("can_resume"):
            st = mr.resume(speed_m_s=speed)
        else:
            st = mr.start(wps, speed_m_s=speed)
    except ValueError as e:
        return {"error": str(e)}, 400
    except Exception as e:
        return {"error": str(e)}, 503
    record("mission_run", f"{v.id}:{len(wps)}@{speed:.1f}")
    return {
        "vehicle_id": v.id,
        "status": "running",
        "start": {"lat": wps[0]["lat"], "lon": wps[0]["lon"]},
        "speed_m_s": speed,
        **st,
    }, 200


@mission_bp.route("/api/mission/run", methods=["POST"])
def run_mission():
    v = _vehicle()
    payload, code = execute_mission_run(v, _request_data())
    return jsonify(payload), code


@mission_bp.route("/api/mission/resume", methods=["POST"])
def resume_mission():
    v = _vehicle()
    data = _request_data()
    if v.control_mode != "autonomous":
        return jsonify({
            "error": "not_autonomous",
            "message": f"Дрон {v.name}: увімкніть «Автономний»",
        }), 409
    speed = _clamp_speed(data.get("speed", 1.0))
    try:
        st = v.mission_runner.resume(speed_m_s=speed)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 503
    return jsonify({"vehicle_id": v.id, "status": "resumed", "speed_m_s": speed, **st})
