"""Метадані маршруту для експорту JSON (поле, оприскування, час)."""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

MISSION_FORMAT_V2 = "gcs_mission_v2"
LEGACY_FORMAT_V1 = "gcs_mission_v1"


def default_record() -> dict:
    return {
        "work_started_at": None,
        "work_finished_at": None,
        "spraying": {
            "applied": False,
            "product": "",
        },
        "field_notes": "",
    }


def normalize_record(raw: Optional[dict]) -> dict:
    base = default_record()
    if not raw:
        return base
    out = deepcopy(base)
    if raw.get("work_started_at"):
        out["work_started_at"] = str(raw["work_started_at"])
    if raw.get("work_finished_at"):
        out["work_finished_at"] = str(raw["work_finished_at"])
    sp = raw.get("spraying") or {}
    if isinstance(sp, dict):
        out["spraying"]["applied"] = bool(sp.get("applied", sp.get("used", False)))
        out["spraying"]["product"] = str(sp.get("product", sp.get("means", "")) or "")
    if raw.get("field_notes") is not None:
        out["field_notes"] = str(raw.get("field_notes", ""))
    return out


def record_from_import(data: dict) -> dict:
    """Злити v1/v2 import у внутрішній record."""
    rec = default_record()
    work = data.get("work") or {}
    if work.get("started_at"):
        rec["work_started_at"] = work["started_at"]
    if work.get("finished_at"):
        rec["work_finished_at"] = work["finished_at"]
    if data.get("work_started_at"):
        rec["work_started_at"] = data["work_started_at"]
    if data.get("work_finished_at"):
        rec["work_finished_at"] = data["work_finished_at"]
    sp = data.get("spraying") or {}
    if isinstance(sp, dict):
        rec["spraying"]["applied"] = bool(sp.get("applied", sp.get("used", False)))
        rec["spraying"]["product"] = str(sp.get("product", sp.get("means", "")) or "")
    if data.get("field_notes") is not None:
        rec["field_notes"] = str(data.get("field_notes", ""))
    return normalize_record(rec)


def export_payload(
    vehicle_id: str,
    waypoints: List[dict],
    record: dict,
    default_speed_m_s: float,
) -> dict:
    rec = normalize_record(record)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    if not rec["work_started_at"]:
        rec["work_started_at"] = now_iso
    return {
        "format": MISSION_FORMAT_V2,
        "vehicle_id": vehicle_id,
        "exported_at": now_iso,
        "default_speed_m_s": float(default_speed_m_s),
        "work": {
            "started_at": rec["work_started_at"],
            "finished_at": rec["work_finished_at"],
        },
        "spraying": {
            "applied": rec["spraying"]["applied"],
            "product": rec["spraying"]["product"],
        },
        "field_notes": rec["field_notes"],
        "waypoints": list(waypoints),
    }


def supported_formats(data: dict) -> bool:
    fmt = data.get("format")
    return fmt in (None, LEGACY_FORMAT_V1, MISSION_FORMAT_V2)
