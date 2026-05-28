"""Віддалений сервер аналізу YOLOv8 — rover відправляє знімки, отримує висновки."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from monitoring.cameras import StereoCapture
from monitoring.config_loader import _root, load_monitoring_config
from monitoring.detector import Detection


@dataclass
class RemoteAnalysisResult:
    detections: List[Detection] = field(default_factory=list)
    model_status: str = "remote"
    message: str = ""
    remote_ok: bool = False
    capture_id: str = ""
    raw: Optional[Dict[str, Any]] = None


def _remote_cfg() -> Dict[str, Any]:
    return load_monitoring_config().get("remote") or {}


def _save_captures(
    capture_id: str,
    stereo: StereoCapture,
) -> None:
    rcfg = _remote_cfg()
    if not rcfg.get("save_captures", True):
        return
    rel = rcfg.get("captures_dir", "data/monitoring/captures")
    out_dir = Path(rel) if Path(rel).is_absolute() else _root() / rel
    out_dir.mkdir(parents=True, exist_ok=True)
    for side_cap in (stereo.left, stereo.right):
        if side_cap.jpeg:
            path = out_dir / f"{capture_id}_{side_cap.side}.jpg"
            path.write_bytes(side_cap.jpeg)


def _parse_detections(payload: Dict[str, Any]) -> List[Detection]:
    out: List[Detection] = []
    for item in payload.get("detections") or []:
        if not isinstance(item, dict):
            continue
        try:
            conf = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        label = str(item.get("label") or "unknown")
        out.append(
            Detection(
                issue_type=str(item.get("issue_type") or "unknown"),
                label=label,
                confidence=conf,
                severity=str(item.get("severity") or _severity_from_conf(conf)),
                camera_side=str(item.get("camera") or item.get("side") or ""),
            )
        )
    return out


def _severity_from_conf(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def check_remote_health() -> Dict[str, Any]:
    rcfg = _remote_cfg()
    mode = (rcfg.get("mode") or "remote").lower()
    if mode == "mock":
        return {"ok": True, "mode": "mock", "message": "Локальна симуляція сервера"}
    if not rcfg.get("enabled", True):
        return {"ok": False, "mode": "off", "message": "Віддалений аналіз вимкнено"}

    base = (rcfg.get("base_url") or "").rstrip("/")
    path = rcfg.get("health_path") or "/health"
    url = f"{base}{path}"
    timeout = float(rcfg.get("timeout_s", 45))
    headers = _auth_headers(rcfg)
    try:
        r = requests.get(url, headers=headers, timeout=min(timeout, 10))
        ok = r.status_code < 400
        return {
            "ok": ok,
            "mode": "remote",
            "status_code": r.status_code,
            "url": url,
            "message": r.text[:200] if not ok else "Сервер доступний",
        }
    except Exception as e:
        return {"ok": False, "mode": "remote", "url": url, "message": str(e)}


def _auth_headers(rcfg: Dict[str, Any]) -> Dict[str, str]:
    key = (rcfg.get("api_key") or "").strip()
    if key:
        return {"Authorization": f"Bearer {key}"}
    return {}


def analyze_stereo_remote(
    stereo: StereoCapture,
    *,
    crop: str,
    vehicle_id: str,
    lat: float,
    lon: float,
    source: str = "survey",
    demo_sim: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> RemoteAnalysisResult:
    """
    Відправити лівий/правий JPEG на сервер.

    Контракт сервера (рекомендований):
      POST {base_url}/api/v1/analyze
      multipart: left_image, right_image (image/jpeg)
      form: crop, vehicle_id, lat, lon, source
      → JSON { detections: [{camera, label, confidence, issue_type, severity}], message }
    """
    rcfg = _remote_cfg()
    mode = (rcfg.get("mode") or "remote").lower()
    capture_id = str(uuid.uuid4())[:12]
    _save_captures(capture_id, stereo)

    if mode == "mock":
        return _mock_analysis(stereo, crop, demo_sim, capture_id)

    if not rcfg.get("enabled", True):
        return RemoteAnalysisResult(
            model_status="off",
            message="remote.enabled=false",
            capture_id=capture_id,
        )

    base = (rcfg.get("base_url") or "").rstrip("/")
    path = rcfg.get("analyze_path") or "/api/v1/analyze"
    url = f"{base}{path}"
    timeout = float(rcfg.get("timeout_s", 45))
    headers = _auth_headers(rcfg)

    files = {}
    if stereo.left.jpeg:
        files["left_image"] = ("left.jpg", stereo.left.jpeg, "image/jpeg")
    if stereo.right.jpeg:
        files["right_image"] = ("right.jpg", stereo.right.jpeg, "image/jpeg")

    if not files:
        return RemoteAnalysisResult(
            model_status="no_images",
            message="Немає знімків з камер",
            capture_id=capture_id,
            remote_ok=False,
        )

    from monitoring.station_config import station_meta

    meta = station_meta()
    ctx = dict(context or {})
    ctx.setdefault("station", meta)
    data = {
        "crop": crop,
        "vehicle_id": vehicle_id,
        "lat": str(lat),
        "lon": str(lon),
        "source": source,
        "capture_id": capture_id,
        "station_id": meta["station_id"],
        "operator": meta["operator"],
        "context_json": json.dumps(ctx, ensure_ascii=False),
    }

    try:
        r = requests.post(
            url,
            data=data,
            files=files,
            headers=headers,
            timeout=timeout,
        )
        r.raise_for_status()
        payload = r.json()
        dets = _parse_detections(payload)
        return RemoteAnalysisResult(
            detections=dets,
            model_status="remote",
            message=str(payload.get("message") or f"OK: {len(dets)} detections"),
            remote_ok=True,
            capture_id=capture_id,
            raw=payload,
        )
    except Exception as e:
        # Зв'язок з сервером відсутній → зберегти у чергу офлайн
        _enqueue_capture_offline(
            capture_id=capture_id,
            stereo=stereo,
            data=data,
            context=ctx,
        )
        return RemoteAnalysisResult(
            model_status="queued",
            message=f"Офлайн: збережено у чергу ({e})",
            capture_id=capture_id,
            remote_ok=False,
        )


def _enqueue_capture_offline(
    *,
    capture_id: str,
    stereo: StereoCapture,
    data: Dict[str, Any],
    context: Dict[str, Any],
) -> None:
    """Зберегти знімок у офлайн-чергу, якщо сервер недоступний."""
    try:
        from monitoring.offline_queue import enqueue_capture

        meta = dict(data)
        meta["context"] = context
        enqueue_capture(
            meta=meta,
            left_jpeg=stereo.left.jpeg,
            right_jpeg=stereo.right.jpeg,
        )
    except Exception as qe:
        print(f"[RemoteClient] offline queue error: {qe}")


def _mock_analysis(
    stereo: StereoCapture,
    crop: str,
    demo_sim: bool,
    capture_id: str,
) -> RemoteAnalysisResult:
    """Симуляція відповіді сервера (без мережі та без YOLO на rover)."""
    cfg = load_monitoring_config()
    dets: List[Detection] = []
    if demo_sim and cfg.get("demo_findings_in_sim", False):
        labels = ((cfg.get("crops") or {}).get(crop) or {}).get("issue_labels") or []
        label = labels[0] if labels else "suspect"
        if stereo.left.frame is not None:
            dets.append(
                Detection(
                    issue_type="disease",
                    label=f"{label}_left",
                    confidence=0.58,
                    severity="low",
                    camera_side="left",
                )
            )
        if stereo.right.frame is not None:
            dets.append(
                Detection(
                    issue_type="pest",
                    label=f"{label}_right",
                    confidence=0.52,
                    severity="low",
                    camera_side="right",
                )
            )
    return RemoteAnalysisResult(
        detections=dets,
        model_status="mock_server",
        message="Mock: віддалений YOLO (симуляція)",
        remote_ok=True,
        capture_id=capture_id,
    )
