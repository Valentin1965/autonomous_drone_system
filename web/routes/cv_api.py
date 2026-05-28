import time

from flask import Blueprint, Response, jsonify

from web.session_log import record
from web.state import drone_state
from web.tracker_service import get_cv_status, get_jpeg_frame, get_tracker, is_running

cv_bp = Blueprint("cv", __name__)

def _placeholder_jpeg() -> bytes:
    import cv2
    import numpy as np

    img = np.zeros((240, 420, 3), dtype=np.uint8)
    img[:] = (30, 40, 50)
    label = "CV ON — кадр…" if is_running() else "CV OFF — натисніть CV ряд"
    cv2.putText(
        img, label, (16, 120),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 200, 220), 2,
    )
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes() if ok else b""


@cv_bp.route("/api/start_tracking", methods=["POST"])
@cv_bp.route("/api/cv/start", methods=["POST"])
def api_start_tracking():
    from flask import request

    from web.fleet import get_fleet, resolve_vehicle_id
    from web.tracker_service import connect_cv, cv_mode

    data = request.get_json(silent=True) or {}
    try:
        vid = resolve_vehicle_id(request, data)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    if cv_mode() == "onboard":
        msg = "CV на борту (RPi): локальний трекер на GCS вимкнено (cv.mode=onboard)."
        record("cv_start_blocked", msg, level="error")
        return jsonify({"status": "error", "message": msg, "mode": "onboard"}), 409

    result = connect_cv(vid, select_vehicle=False)
    code = 503 if result.get("status") == "error" else 200
    if result.get("status") == "error":
        record("cv_start_failed", result.get("message", ""), level="error")
    else:
        record("cv_start", f"{vid}:{result.get('source', '')}")
    return jsonify(result), code


@cv_bp.route("/api/stop_tracking", methods=["POST"])
@cv_bp.route("/api/cv/stop", methods=["POST"])
def api_stop_tracking():
    from flask import request

    from web.fleet import resolve_vehicle_id
    from web.tracker_service import disconnect_cv

    data = request.get_json(silent=True) or {}
    vid = data.get("vehicle_id") or data.get("id")
    if not vid and request.args.get("vehicle_id"):
        vid = request.args.get("vehicle_id")
    result = disconnect_cv(str(vid) if vid else None)
    record("cv_stop", result.get("vehicle_id", ""))
    return jsonify(result)


@cv_bp.route("/api/cv/target", methods=["POST"])
def api_cv_target():
    """Optional: set target class name (future use)."""
    from flask import request

    data = request.get_json(silent=True) or {}
    target = data.get("target", "")
    t = get_tracker() if _tracker_exists() else None
    if t and target:
        t.cfg.setdefault("classes", {})["follow"] = target
    return jsonify({"target": target or "traversable"})


def _tracker_exists():
    from web import tracker_service
    return tracker_service._tracker is not None


@cv_bp.route("/api/cv/snapshot")
def api_cv_snapshot():
    frame = get_jpeg_frame() if is_running() else None
    if not frame:
        frame = _placeholder_jpeg()
    return Response(frame, mimetype="image/jpeg")


@cv_bp.route("/api/cv/stream")
def api_cv_stream():
    """MJPEG для <img src=/api/cv/stream>."""

    def generate():
        boundary = b"--frame\r\n"
        while True:
            frame = get_jpeg_frame() if is_running() else None
            if not frame:
                frame = _placeholder_jpeg()
            yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.08)

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@cv_bp.route("/api/cv/status", methods=["GET"])
def api_cv_status():
    st = get_cv_status()
    st["motion"] = "in_process" if st.get("running") else None
    st["emergency_stop"] = drone_state.emergency_stop
    return jsonify(st)
