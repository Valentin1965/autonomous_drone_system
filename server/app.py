"""
Flask-застосунок аналітичного сервера.

Один сервер — багато станцій.
Не залежить від web/, monitoring/, simulator/ — окремий блок.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, render_template, request

from server import config as cfg
from server import database as db
from server import yolo_engine as yolo

app = Flask(__name__)


def _check_auth() -> Optional[Tuple[dict, int]]:
    key = cfg.api_key()
    if not key:
        return None
    auth = request.headers.get("Authorization", "")
    if auth.strip() != f"Bearer {key}":
        return {"error": "unauthorized", "message": "Invalid Authorization token"}, 401
    return None


def _parse_context() -> Dict[str, Any]:
    raw = request.form.get("context_json") or ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _save_jpeg(capture_id: str, side: str, data: bytes) -> str:
    folder = cfg.captures_dir() / capture_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{side}.jpg"
    path.write_bytes(data)
    root = cfg.captures_dir().parent.parent
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# ─── Info / health ─────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return jsonify(
        {
            "service": "fleet-analysis-server",
            "description": "YOLOv8 + SQLite: моніторинг і журнал роботи флоту (bagato станцій → один сервер)",
            "endpoints": {
                "GET  /health": "стан сервера + статистика БД",
                "GET  /api/v1/stats": "лічильники таблиць",
                "POST /api/v1/analyze": "знімки з дрона → YOLO → БД",
                "POST /api/v1/events": "події станції (маршрут, sprayer, обстеження)",
                "GET  /api/v1/findings": "висновки YOLO (фільтри: station_id, vehicle_id, crop)",
                "GET  /api/v1/operations": "журнал подій (фільтри: station_id, vehicle_id, event_type)",
                "GET  /api/v1/spray/coverage": "оброблена ділянка (spray on/off + GPS)",
            },
            "models_loaded": yolo.models_loaded(),
            "database": db.stats(),
        }
    )


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Простий UI поверх /api/v1/stats, /findings, /operations."""
    return render_template("dashboard.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "fleet-analysis-server",
            "models_loaded": yolo.models_loaded(),
            "database": db.stats(),
        }
    )


@app.route("/api/v1/stats", methods=["GET"])
def api_stats():
    auth = _check_auth()
    if auth:
        return jsonify(auth[0]), auth[1]
    return jsonify({"status": "ok", **db.stats()})


# ─── Analyze (станція → сервер: JPEG + контекст) ───────────────────────────

@app.route("/api/v1/analyze", methods=["POST"])
def api_analyze():
    auth = _check_auth()
    if auth:
        return jsonify(auth[0]), auth[1]

    crop = request.form.get("crop", "vineyard")
    vehicle_id = request.form.get("vehicle_id", "")
    station_id = request.form.get("station_id", "")
    operator = request.form.get("operator", "")
    source = request.form.get("source", "survey")
    capture_id = request.form.get("capture_id") or str(uuid.uuid4())[:12]
    context = _parse_context()

    try:
        lat = float(request.form.get("lat") or 0)
        lon = float(request.form.get("lon") or 0)
    except (TypeError, ValueError):
        lat, lon = 0.0, 0.0

    # Зберегти JPEG на диск сервера
    left_path = right_path = ""
    image_bytes: Dict[str, bytes] = {}
    for field, side in (("left_image", "left"), ("right_image", "right")):
        f = request.files.get(field)
        if not f:
            continue
        data = f.read()
        if data:
            image_bytes[side] = data
            rel = _save_jpeg(capture_id, side, data)
            if side == "left":
                left_path = rel
            else:
                right_path = rel

    # YOLO inference
    model = yolo.model_for(crop)
    detections: List[dict] = []
    message = ""

    if model is None:
        message = (
            f"No model for crop='{crop}'. "
            "Capture saved, inference skipped. "
            "Start server with --vineyard-weights / --default-weights."
        )
    else:
        for side, data in image_bytes.items():
            img = yolo.decode_jpeg(data)
            if img is None:
                detections.append(
                    {
                        "camera": side,
                        "label": "decode_failed",
                        "confidence": 0.0,
                        "issue_type": "unknown",
                        "severity": "low",
                    }
                )
                continue
            for d in yolo.run(model, img)[:20]:
                detections.append({"camera": side, **d})
        message = f"Analyzed {len(image_bytes)} image(s) — {len(detections)} detection(s)"

    # Зберегти у БД
    db.insert_capture(
        capture_id=capture_id,
        station_id=station_id,
        operator=operator,
        vehicle_id=vehicle_id,
        crop=crop,
        lat=lat,
        lon=lon,
        source=source,
        left_image_path=left_path,
        right_image_path=right_path,
        context=context,
        analysis_message=message,
    )
    db.insert_detections(capture_id, detections)
    db.insert_fleet_event(
        event_type="monitoring_capture",
        station_id=station_id,
        operator=operator,
        vehicle_id=vehicle_id,
        lat=lat,
        lon=lon,
        detail=message,
        payload={
            "capture_id": capture_id,
            "crop": crop,
            "source": source,
            "detection_count": len(detections),
            "mission_phase": (context.get("vehicle") or {})
            .get("mission", {})
            .get("phase"),
        },
    )

    return jsonify(
        {
            "status": "ok",
            "capture_id": capture_id,
            "crop": crop,
            "vehicle_id": vehicle_id,
            "station_id": station_id,
            "operator": operator,
            "lat": lat,
            "lon": lon,
            "detections": detections,
            "message": message,
            "stored": True,
        }
    )


# ─── Events (станція → сервер: без фото) ───────────────────────────────────

@app.route("/api/v1/events", methods=["POST"])
def api_events():
    """
    Прийняти подію роботи флоту:
    маршрут, оприскування, старт/кінець обстеження, оператор тощо.
    Дані надходять у JSON (не multipart).
    """
    auth = _check_auth()
    if auth:
        return jsonify(auth[0]), auth[1]

    data = request.get_json(silent=True) or {}
    lat = data.get("lat")
    lon = data.get("lon")
    row_id = db.insert_fleet_event(
        event_type=str(data.get("event_type") or "unknown"),
        station_id=str(data.get("station_id") or ""),
        operator=str(data.get("operator") or ""),
        vehicle_id=str(data.get("vehicle_id") or ""),
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        detail=str(data.get("detail") or ""),
        payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
    )
    return jsonify({"status": "ok", "id": row_id})


# ─── Query ─────────────────────────────────────────────────────────────────

@app.route("/api/v1/findings", methods=["GET"])
def api_findings():
    auth = _check_auth()
    if auth:
        return jsonify(auth[0]), auth[1]
    items = db.list_findings(
        station_id=request.args.get("station_id"),
        vehicle_id=request.args.get("vehicle_id"),
        crop=request.args.get("crop"),
        limit=int(request.args.get("limit", 200)),
    )
    return jsonify({"status": "ok", "findings": items, "count": len(items)})


@app.route("/api/v1/operations", methods=["GET"])
def api_operations():
    auth = _check_auth()
    if auth:
        return jsonify(auth[0]), auth[1]
    items = db.list_operations(
        station_id=request.args.get("station_id"),
        vehicle_id=request.args.get("vehicle_id"),
        event_type=request.args.get("event_type"),
        limit=int(request.args.get("limit", 100)),
    )
    return jsonify({"status": "ok", "operations": items, "count": len(items)})


@app.route("/api/v1/spray/coverage", methods=["GET"])
def api_spray_coverage():
    """Сесії оприскування + зв'язок із моніторингом (findings)."""
    auth = _check_auth()
    if auth:
        return jsonify(auth[0]), auth[1]
    swath = float(request.args.get("swath_width_m", 2.0))
    summary = spray_cov.coverage_summary(
        station_id=request.args.get("station_id"),
        vehicle_id=request.args.get("vehicle_id"),
        limit=int(request.args.get("limit", 500)),
        default_swath_m=swath,
    )
    return jsonify({"status": "ok", **summary})
