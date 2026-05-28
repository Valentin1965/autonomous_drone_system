"""API моніторингу рослин — окремий блок від маршруту / CV ряду."""

from flask import Blueprint, jsonify, request

from web.fleet import get_fleet, resolve_vehicle_id
from web.session_log import record

monitoring_bp = Blueprint("monitoring", __name__)


def _data():
    return request.get_json(silent=True) or {}


def _vehicle():
    vid = resolve_vehicle_id(request, _data())
    return get_fleet().get_vehicle(vid)


def _preflight_block(vehicle):
    """Preflight для зйомки / обстеження (GPS, ARM, e-stop; без вимоги маршруту)."""
    from web.preflight import assert_ready_for_cv

    try:
        st = vehicle.get_controller().get_status()
        gps = dict(st.get("gps") or {})
        try:
            from simulator import fleet_registry

            sim_gps = fleet_registry.get_position(vehicle.id)
            if sim_gps:
                gps = dict(sim_gps)
        except Exception:
            pass
        st = {**st, "gps": gps}
        pre = assert_ready_for_cv(vehicle, mavlink_status=st)
        if pre:
            return pre, 409
    except Exception as e:
        return {"error": "preflight_failed", "message": str(e)}, 503
    return None, 200


@monitoring_bp.route("/api/monitoring/station", methods=["GET"])
def api_monitoring_station_get():
    from monitoring.station_config import station_meta

    meta = station_meta()
    return jsonify({
        "station_id": meta["station_id"],
        "operator": meta["operator"],
    })


@monitoring_bp.route("/api/monitoring/station", methods=["PUT", "POST"])
def api_monitoring_station_put():
    from monitoring.station_config import save_runtime_station, station_meta

    data = _data()
    sid = str(data.get("station_id") or data.get("id") or "").strip()
    op = str(data.get("operator", "")).strip()
    current = station_meta()
    if not sid:
        sid = current["station_id"]
    save_runtime_station(station_id=sid, operator=op)
    record("monitoring_station", f"{sid}:{op or '—'}")
    meta = station_meta()
    return jsonify({
        "status": "ok",
        "station_id": meta["station_id"],
        "operator": meta["operator"],
    })


@monitoring_bp.route("/api/monitoring/preflight", methods=["GET"])
def api_monitoring_preflight():
    """Preflight для зйомки / обстеження (без вимоги маршруту)."""
    from web.preflight import evaluate

    v = _vehicle()
    try:
        st = v.get_controller().get_status()
        gps = dict(st.get("gps") or {})
        try:
            from simulator import fleet_registry

            sim_gps = fleet_registry.get_position(v.id)
            if sim_gps:
                gps = dict(sim_gps)
        except Exception:
            pass
        st = {**st, "gps": gps}
        pf = evaluate(v, mavlink_status=st, require_route=False, require_arm=True)
    except Exception as e:
        return jsonify({"error": str(e), "ready_for_cv": False}), 503

    if not pf.get("ready_for_cv"):
        return jsonify(
            {
                "ready_for_cv": False,
                "block_reason": pf.get("block_reason") or "Не готово до моніторингу",
                "preflight": pf,
            }
        ), 409
    return jsonify({"ready_for_cv": True, "preflight": pf})


@monitoring_bp.route("/api/monitoring/upload", methods=["POST"])
def api_monitoring_upload():
    """
    RPi → станція: JPEG лівої/правої камери моніторингу.
    multipart: vehicle_id, side (left|right), image (file); опційно token.
    """
    from monitoring.rpi_uplink import (
        is_rpi_source,
        store_upload,
        upload_token_expected,
    )

    if not is_rpi_source():
        return jsonify({
            "error": "uplink_not_rpi",
            "message": "uplink.source не rpi — завантаження вимкнено",
        }), 409

    expected = upload_token_expected()
    if expected:
        got = (
            request.headers.get("X-Upload-Token")
            or request.form.get("token")
            or ""
        ).strip()
        if got != expected:
            return jsonify({"error": "invalid_token"}), 403

    vehicle_id = (request.form.get("vehicle_id") or "rover_1").strip()
    side = (request.form.get("side") or "").strip().lower()
    if side not in ("left", "right"):
        return jsonify({"error": "side must be left or right"}), 400

    f = request.files.get("image") or request.files.get("file")
    if not f:
        return jsonify({"error": "image file required"}), 400

    jpeg = f.read()
    if not jpeg:
        return jsonify({"error": "empty image"}), 400

    try:
        store_upload(vehicle_id, side, jpeg)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    from monitoring.rpi_uplink import buffer_status

    return jsonify({
        "status": "ok",
        "vehicle_id": vehicle_id,
        "side": side,
        "bytes": len(jpeg),
        "buffer": buffer_status(vehicle_id),
    })


@monitoring_bp.route("/api/monitoring/uplink/status", methods=["GET"])
def api_monitoring_uplink_status():
    from monitoring.rpi_uplink import buffer_status, is_rpi_source, uplink_source

    vid = request.args.get("vehicle_id")
    return jsonify({
        "source": uplink_source(),
        "is_rpi": is_rpi_source(),
        "buffers": buffer_status(vid) if vid else buffer_status(),
    })


@monitoring_bp.route("/api/monitoring/config", methods=["GET"])
def api_monitoring_config():
    from monitoring.service import get_monitoring_service

    svc = get_monitoring_service()
    return jsonify(svc.public_config())


@monitoring_bp.route("/api/monitoring/cameras", methods=["GET"])
def api_monitoring_cameras():
    from monitoring.cameras import get_camera_rig

    return jsonify(get_camera_rig().status())


@monitoring_bp.route("/api/monitoring/remote/health", methods=["GET"])
def api_monitoring_remote_health():
    from monitoring.remote_client import check_remote_health

    return jsonify(check_remote_health())


@monitoring_bp.route("/api/monitoring/crop", methods=["PUT", "POST"])
def api_monitoring_crop():
    from monitoring.service import get_monitoring_service

    data = _data()
    crop = (data.get("crop") or data.get("crop_id") or "").strip()
    if not crop:
        return jsonify({"error": "crop required"}), 400
    try:
        svc = get_monitoring_service()
        svc.set_crop(crop)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    record("monitoring_crop", crop)
    return jsonify({"crop": crop, "config": svc.public_config()})


@monitoring_bp.route("/api/monitoring/status", methods=["GET"])
def api_monitoring_status():
    from monitoring.service import get_monitoring_service

    vid = request.args.get("vehicle_id")
    svc = get_monitoring_service()
    return jsonify(svc.status(vehicle_id=vid))


@monitoring_bp.route("/api/monitoring/findings", methods=["GET"])
def api_monitoring_findings():
    from monitoring.service import get_monitoring_service

    svc = get_monitoring_service()
    vid = request.args.get("vehicle_id")
    crop = request.args.get("crop")
    limit = int(request.args.get("limit", 200))
    items = svc.list_findings(vehicle_id=vid, crop=crop, limit=limit)
    return jsonify({"count": len(items), "findings": items})


@monitoring_bp.route("/api/monitoring/findings", methods=["DELETE"])
def api_monitoring_clear():
    from monitoring.service import get_monitoring_service

    data = _data()
    svc = get_monitoring_service()
    removed = svc.clear(
        vehicle_id=data.get("vehicle_id"),
        crop=data.get("crop"),
    )
    record("monitoring_clear", str(removed))
    return jsonify({"removed": removed})


@monitoring_bp.route("/api/monitoring/survey/start", methods=["POST"])
def api_survey_start():
    from monitoring.service import get_monitoring_service

    data = _data()
    v = _vehicle()
    svc = get_monitoring_service()
    if data.get("crop"):
        try:
            svc.set_crop(str(data["crop"]))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    wps = None
    if data.get("waypoints"):
        wps = []
        for wp in data["waypoints"]:
            if wp.get("lat") is None or wp.get("lon") is None:
                continue
            wps.append({"lat": float(wp["lat"]), "lon": float(wp["lon"])})

    pre, code = _preflight_block(v)
    if pre:
        return jsonify(pre), code

    try:
        st = svc.start_survey(v, waypoints=wps)
    except ValueError as e:
        return jsonify({"error": "survey_failed", "message": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    record("monitoring_survey_start", f"{v.id}:{st.get('total', 0)}")
    return jsonify({"vehicle_id": v.id, **st})


@monitoring_bp.route("/api/monitoring/survey/stop", methods=["POST"])
def api_survey_stop():
    from monitoring.service import get_monitoring_service

    v = _vehicle()
    st = get_monitoring_service().stop_survey(v)
    record("monitoring_survey_stop", v.id)
    return jsonify({"vehicle_id": v.id, **st})


@monitoring_bp.route("/api/monitoring/sample", methods=["POST"])
def api_monitoring_sample():
    """Аналіз на поточній позиції без руху по маршруту."""
    from monitoring.service import get_monitoring_service

    data = _data()
    v = _vehicle()
    svc = get_monitoring_service()
    if data.get("crop"):
        try:
            svc.set_crop(str(data["crop"]))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    pre, code = _preflight_block(v)
    if pre:
        return jsonify(pre), code

    try:
        result = svc.sample_now(v)
    except Exception as e:
        return jsonify({"error": str(e)}), 503
    record("monitoring_sample", f"{v.id}:{len(result.get('findings', []))}")
    return jsonify(result)


@monitoring_bp.route("/api/monitoring/spray/coverage", methods=["GET"])
def api_monitoring_spray_coverage():
    """Локальний трек оприскування (GPS + час spray) для обраного дрона."""
    from monitoring.spray_coverage import vehicle_summary

    v = _vehicle()
    return jsonify({"status": "ok", "coverage": vehicle_summary(v.id)})


@monitoring_bp.route("/api/monitoring/queue", methods=["GET"])
def api_monitoring_queue():
    """Статус офлайн-черги відправки на сервер."""
    try:
        from monitoring.offline_queue import queue_status

        return jsonify({"status": "ok", **queue_status()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@monitoring_bp.route("/api/monitoring/queue/flush", methods=["POST"])
def api_monitoring_queue_flush():
    """Примусово спробувати відправити чергу негайно."""
    try:
        from monitoring.offline_queue import flush

        n = flush()
        return jsonify({"status": "ok", "flushed": n})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
