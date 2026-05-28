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


def _mission_public(v):
    draft = None
    if v.mission_draft and not v.mission_route_committed:
        draft = {
            "waypoints": list(v.mission_draft.get("waypoints") or []),
            "planning": v.mission_draft.get("planning"),
            "segments": v.mission_draft.get("segments"),
        }
    return {
        "vehicle_id": v.id,
        "waypoints": list(_waypoints(v)),
        "draft": draft,
        "route_committed": bool(v.mission_route_committed),
        "record": normalize_record(v.mission_record),
    }


@mission_bp.route("/api/mission", methods=["GET"])
def get_mission():
    return jsonify(_mission_public(_vehicle()))


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


@mission_bp.route("/api/mission/plan/defaults", methods=["GET"])
def mission_plan_defaults():
    """Параметри за замовчуванням для планувальника рядів (ground rover)."""
    from config.geo_defaults import DEFAULT_LAT, DEFAULT_LON
    from planning.mission_waypoints import GROUND_ROVER_DEFAULTS

    v = _vehicle()
    mcfg = drone_state.load_config().get("mission", {})
    return jsonify({
        "vehicle_id": v.id,
        "origin_lat": float(getattr(v, "start_lat", None) or DEFAULT_LAT),
        "origin_lon": float(getattr(v, "start_lon", None) or DEFAULT_LON),
        "azimuth_deg": 0.0,
        "row_spacing_m": 1.0,
        "row_length_m": 50.0,
        "row_count": 5,
        "use_zigzag": GROUND_ROVER_DEFAULTS["use_zigzag"],
        "turn_point_offset_m": GROUND_ROVER_DEFAULTS["turn_point_offset_m"],
        "densify_step_m": GROUND_ROVER_DEFAULTS["densify_step_m"],
        "default_speed_m_s": float(mcfg.get("default_speed_m_s", 1.0)),
        "add_takeoff": False,
        "add_rtl": False,
        "navigation_note": (
            "GPS waypoints між рядами; точність ~1 m у ряду — RTK + CV hybrid на полі."
        ),
    })


@mission_bp.route("/api/mission/plan-rows", methods=["POST"])
def plan_vineyard_rows():
    """
    Планувальник: паралельні ряди (ENU) → waypoints WGS84 → gcs_mission_v2.
    body.store_draft=true (або apply=true) — лише чернетка на сервері;
    фіксований маршрут (реальні GPS) — після першого проходу першого ряду.
    """
    from planning.field_plan import FieldPlanRequest, plan_field_from_polygon, plan_vineyard_field
    from planning.mission_waypoints import strip_roles

    v = _vehicle()
    data = _request_data()
    if not _route_editable(v):
        return _route_locked_response()

    if data.get("origin_lat") is None:
        data = dict(data)
        data.setdefault("origin_lat", v.start_lat)
        data.setdefault("origin_lon", v.start_lon)
    data.setdefault("vehicle_id", v.id)

    try:
        req = FieldPlanRequest.from_dict(data)
        req.vehicle_id = v.id
        use_field = bool(data.get("use_field", False))
        if use_field:
            from web.field import polygon as field_polygon

            poly = field_polygon()
            if not poly:
                return jsonify({
                    "error": "no_field_polygon",
                    "message": "Контур поля не задано. Увімкніть «Контур поля» і додайте точки.",
                }), 409
            # якщо use_field=true, але азимут не задано — автоазимут за замовч.
            if data.get("auto_azimuth") is None and not data.get("azimuth_deg"):
                req.auto_azimuth = True
            result = plan_field_from_polygon(req, poly)
        else:
            result = plan_vineyard_field(req)
    except (TypeError, ValueError, KeyError) as e:
        return jsonify({"error": "invalid_plan_request", "message": str(e)}), 400

    nav_wps = result["waypoints_nav"]
    store_draft = bool(
        data.get("store_draft", data.get("apply", False))
    )

    if store_draft:
        from web import geofence

        for wp in nav_wps:
            ok, msg = geofence.check_position(wp["lat"], wp["lon"])
            if not ok:
                return jsonify({
                    "error": "geofence",
                    "message": msg,
                    "waypoint": wp,
                }), 400
        v.set_mission_draft(
            result["waypoints"],
            planning=result.get("planning"),
            segments=result.get("segments"),
        )
        if req.field_notes:
            v.mission_record["field_notes"] = req.field_notes
        record("mission_plan_draft", f"{v.id}:{len(nav_wps)} wp")

    out = {
        "vehicle_id": v.id,
        "store_draft": store_draft,
        "route_committed": v.mission_route_committed,
        "stats": result["stats"],
        "planning": result["planning"],
        "segments": result["segments"],
        "waypoints": result["waypoints"],
        "waypoints_nav": nav_wps,
        "gcs_mission": result["gcs_mission"],
    }
    return jsonify(out)


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
    v.mission_route_committed = True
    v.clear_mission_draft()
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
    # Не можна "snap to start" під час місії — інакше зупиняє/телепортує інші дрони у флоті.
    try:
        phase = v.mission_runner.status().get("phase", "idle")
        if phase in ("running", "returning", "paused"):
            return jsonify({
                "synced": False,
                "reason": "mission_active",
                "vehicle_id": v.id,
                "phase": phase,
            }), 409
    except Exception:
        pass
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
    v.mission_route_committed = True
    v.clear_mission_draft()
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
    from web import geofence

    ok, msg = geofence.check_position(wp["lat"], wp["lon"])
    if not ok:
        return jsonify({"error": "geofence", "message": msg}), 400
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
    from web import geofence

    ok, msg = geofence.check_position(wp["lat"], wp["lon"])
    if not ok:
        return jsonify({"error": "geofence", "message": msg}), 400
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
    v.clear_mission_draft()
    v.mission_route_committed = False
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
    from config.geo_defaults import DEFAULT_LAT, DEFAULT_LON, DEFAULT_MAP_ZOOM

    cfg = drone_state.load_config()
    gcs_cfg = cfg.get("gcs") or {}
    return jsonify({
        "default_speed_m_s": float(mcfg.get("default_speed_m_s", 1.0)),
        "min_speed_m_s": float(mcfg.get("min_speed_m_s", 0.3)),
        "max_speed_m_s": float(mcfg.get("max_speed_m_s", 3.0)),
        "presets": {
            "spray_m_s": float(presets.get("spray_m_s", 0.8)),
            "row_m_s": float(presets.get("row_m_s", 1.0)),
            "transfer_m_s": float(presets.get("transfer_m_s", 1.5)),
        },
        "geofence": _geofence_public(),
        "map": {
            "center_lat": float(gcs_cfg.get("default_center_lat", DEFAULT_LAT)),
            "center_lon": float(gcs_cfg.get("default_center_lon", DEFAULT_LON)),
            "zoom": int(gcs_cfg.get("default_zoom", DEFAULT_MAP_ZOOM)),
            "label": "Tenerife, Canary Islands",
        },
    })


def _geofence_public():
    from web.geofence import public_config

    return public_config()


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
    from web.preflight import assert_ready_for_mission

    from web.mission_route import normalize_route_wp

    if data.get("waypoints"):
        cleaned = []
        for wp in data["waypoints"]:
            if wp.get("lat") is None or wp.get("lon") is None:
                continue
            cleaned.append(normalize_route_wp(wp))
        if not v.mission_route_committed and (
            data.get("draft_only") or data.get("store_draft")
        ):
            v.set_mission_draft(
                cleaned,
                planning=data.get("planning"),
                segments=data.get("segments"),
            )
        elif not data.get("draft_only"):
            v.mission_waypoints = [
                {"lat": w["lat"], "lon": w["lon"]} for w in cleaned
            ]
            v.mission_route_committed = True
            v.clear_mission_draft()

    if v.control_mode != "autonomous":
        return {
            "error": "not_autonomous",
            "message": f"Дрон {v.name}: увімкніть «Автономний»",
        }, 409

    wps = v.get_execution_waypoints()
    if not wps:
        return {
            "error": "empty mission",
            "message": "Додайте точки на карті або згенеруйте ряди (чернетка)",
        }, 400
    try:
        from monitoring.service import get_monitoring_service

        surv = get_monitoring_service().status(vehicle_id=v.id)
        sst = (surv.get("surveys") or {}).get(v.id) or {}
        if sst.get("active"):
            return {
                "error": "survey_active",
                "message": "Зупиніть обстеження (■ Стоп обстеж.) перед GPS-маршрутом",
            }, 409
    except Exception:
        pass

    mr = v.mission_runner
    if len(wps) < 2 and not mr.status().get("can_resume"):
        return {
            "error": "need_two_waypoints",
            "message": "Потрібно мінімум 2 точки: перша — старт, далі рух по маршруту",
        }, 400

    from web.vehicle_prep import prepare_for_motion

    prepare_for_motion(v)
    st = v.get_controller().get_status()
    pre = assert_ready_for_mission(v, mavlink_status=st)
    if pre:
        return pre, 409

    speed = _clamp_speed(data.get("speed", 1.0))
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
    try:
        from monitoring.event_uplink import push_vehicle_event

        push_vehicle_event(
            v,
            "mission_run",
            detail=f"{len(wps)} точок @ {speed:.1f} m/s",
            payload={
                "waypoint_count": len(wps),
                "speed_m_s": speed,
                "waypoints": wps[:50],
            },
        )
    except Exception:
        pass
    return {
        "vehicle_id": v.id,
        "status": "running",
        "start": {"lat": wps[0]["lat"], "lon": wps[0]["lon"]},
        "speed_m_s": speed,
        "route_committed": v.mission_route_committed,
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
    from web.preflight import assert_ready_for_mission
    from web.vehicle_prep import prepare_for_motion

    prepare_for_motion(v)
    st = v.get_controller().get_status()
    pre = assert_ready_for_mission(v, mavlink_status=st)
    if pre:
        return jsonify(pre), 409
    speed = _clamp_speed(data.get("speed", 1.0))
    try:
        st = v.mission_runner.resume(speed_m_s=speed)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 503
    return jsonify({"vehicle_id": v.id, "status": "resumed", "speed_m_s": speed, **st})
