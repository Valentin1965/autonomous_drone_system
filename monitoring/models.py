"""Моделі даних моніторингу."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_finding(
    *,
    crop: str,
    vehicle_id: str,
    lat: float,
    lon: float,
    issue_type: str,
    label: str,
    confidence: float,
    severity: str = "medium",
    source: str = "survey",
    note: str = "",
    camera_side: str = "",
    capture_id: str = "",
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "crop": crop,
        "vehicle_id": vehicle_id,
        "lat": float(lat),
        "lon": float(lon),
        "issue_type": issue_type,
        "label": label,
        "confidence": round(float(confidence), 4),
        "severity": severity,
        "source": source,
        "note": note,
        "camera_side": camera_side,
        "capture_id": capture_id,
        "created_at": _utc_now(),
    }


def normalize_finding(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(raw.get("id") or uuid.uuid4()),
        "crop": str(raw.get("crop") or "vineyard"),
        "vehicle_id": str(raw.get("vehicle_id") or ""),
        "lat": float(raw.get("lat", 0)),
        "lon": float(raw.get("lon", 0)),
        "issue_type": str(raw.get("issue_type") or "unknown"),
        "label": str(raw.get("label") or "unknown"),
        "confidence": float(raw.get("confidence", 0)),
        "severity": str(raw.get("severity") or "medium"),
        "source": str(raw.get("source") or "survey"),
        "note": str(raw.get("note") or ""),
        "camera_side": str(raw.get("camera_side") or ""),
        "capture_id": str(raw.get("capture_id") or ""),
        "created_at": raw.get("created_at") or _utc_now(),
    }


def crop_public(cfg: Dict[str, Any], crop_id: str) -> Dict[str, Any]:
    crops = cfg.get("crops") or {}
    c = crops.get(crop_id) or {}
    return {
        "id": crop_id,
        "name": c.get("name", crop_id),
        "labels": list(c.get("issue_labels") or []),
    }


def list_crops_public(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    crops = cfg.get("crops") or {}
    return [crop_public(cfg, cid) for cid in crops.keys()]
