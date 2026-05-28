"""Поля (полігони) для планування рядів, коли даних на сервері ще нема."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from shapely.geometry import Polygon
from shapely.validation import explain_validity

_FIELDS: Optional[List[Dict[str, Any]]] = None
_ACTIVE_ID: Optional[str] = None
_OPERATOR_SET: bool = False

_MIN_POINTS = 3


def _merge_config() -> dict:
    try:
        from web.field_store import load_runtime

        runtime = load_runtime() or {}
    except Exception:
        runtime = {}
    return runtime if isinstance(runtime, dict) else {}


def _load() -> None:
    global _FIELDS, _ACTIVE_ID, _OPERATOR_SET
    if _FIELDS is not None:
        return
    cfg = _merge_config()
    _OPERATOR_SET = bool(cfg.get("operator_set", False)) or _has_runtime_file()
    fields = cfg.get("fields") or []
    _ACTIVE_ID = cfg.get("active_field_id")
    if not isinstance(fields, list):
        fields = []
    out_fields: List[Dict[str, Any]] = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "").strip()
        name = str(f.get("name") or fid or "Field").strip()
        enabled = bool(f.get("enabled", True))
        poly = f.get("polygon") or []
        try:
            pts = normalize_polygon(poly, validate=True)
        except ValueError:
            pts = []
            enabled = False
        out_fields.append(
            {
                "id": fid or f"field_{len(out_fields)+1}",
                "name": name,
                "enabled": enabled and len(pts) >= _MIN_POINTS,
                "polygon": pts,
                "updated_at": f.get("updated_at"),
            }
        )
    _FIELDS = out_fields
    if _ACTIVE_ID and not any(x["id"] == _ACTIVE_ID for x in _FIELDS):
        _ACTIVE_ID = None


def _has_runtime_file() -> bool:
    from web.field_store import RUNTIME_PATH

    return RUNTIME_PATH.is_file()


def reload() -> None:
    global _FIELDS
    _FIELDS = None
    _load()


def is_enabled() -> bool:
    _load()
    return bool(active_field())


def fields() -> List[Dict[str, Any]]:
    _load()
    return list(_FIELDS or [])


def active_field_id() -> Optional[str]:
    _load()
    return _ACTIVE_ID


def active_field() -> Optional[Dict[str, Any]]:
    _load()
    if not _ACTIVE_ID:
        # fallback: first enabled
        for f in _FIELDS or []:
            if f.get("enabled") and (f.get("polygon") or []):
                return f
        return None
    for f in _FIELDS or []:
        if f.get("id") == _ACTIVE_ID:
            return f if f.get("enabled") else None
    return None


def polygon() -> List[Dict[str, float]]:
    f = active_field()
    return list((f or {}).get("polygon") or [])


def public_config() -> Dict[str, Any]:
    _load()
    act = active_field()
    return {
        "operator_set": _OPERATOR_SET,
        "active_field_id": _ACTIVE_ID,
        "fields": [
            {"id": f["id"], "name": f["name"], "enabled": bool(f.get("enabled"))}
            for f in (fields() or [])
        ],
        "active": {
            "id": act.get("id") if act else None,
            "name": act.get("name") if act else None,
            "enabled": bool(act.get("enabled")) if act else False,
            "polygon": list(act.get("polygon") or []) if act else [],
        },
    }


def normalize_polygon(points: List[dict], *, validate: bool = False) -> List[Dict[str, float]]:
    if not isinstance(points, list) or len(points) < _MIN_POINTS:
        raise ValueError("Контур поля: потрібно мінімум 3 точки")
    out: List[Dict[str, float]] = []
    for p in points:
        try:
            out.append({"lat": float(p["lat"]), "lon": float(p["lon"])})
        except Exception:
            continue
    if len(out) < _MIN_POINTS:
        raise ValueError("Контур поля: некоректні точки")
    # якщо остання = перша — приберемо дубль
    if (
        len(out) >= 4
        and abs(out[0]["lat"] - out[-1]["lat"]) < 1e-10
        and abs(out[0]["lon"] - out[-1]["lon"]) < 1e-10
    ):
        out.pop()
    if len(out) < _MIN_POINTS:
        raise ValueError("Контур поля: замало точок")
    if validate:
        poly = Polygon([(p["lon"], p["lat"]) for p in out])
        if not poly.is_valid:
            raise ValueError("Контур поля: " + explain_validity(poly))
    return out


def _save_fields(active_id: Optional[str], items: List[Dict[str, Any]]) -> None:
    from web.field_store import save_runtime

    payload = {"version": 2, "operator_set": True, "active_field_id": active_id, "fields": items}
    save_runtime(payload)


def create_field(name: str, points: List[dict]) -> Dict[str, Any]:
    poly = normalize_polygon(points, validate=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    fid = f"field_{uuid.uuid4().hex[:8]}"
    items = fields()
    items.append({"id": fid, "name": str(name or fid), "enabled": True, "polygon": poly, "updated_at": now})
    _save_fields(fid, items)
    reload()
    return public_config()


def update_field(field_id: str, *, name: Optional[str] = None, points: Optional[List[dict]] = None) -> Dict[str, Any]:
    fid = str(field_id or "").strip()
    if not fid:
        raise ValueError("field_id required")
    items = fields()
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    found = False
    for f in items:
        if f.get("id") != fid:
            continue
        found = True
        if name is not None:
            f["name"] = str(name).strip() or f.get("name") or fid
        if points is not None:
            f["polygon"] = normalize_polygon(points, validate=True)
            f["enabled"] = True
        f["updated_at"] = now
        break
    if not found:
        raise ValueError("field not found")
    _save_fields(active_field_id(), items)
    reload()
    return public_config()


def select_field(field_id: str) -> Dict[str, Any]:
    fid = str(field_id or "").strip()
    if not fid:
        raise ValueError("field_id required")
    items = fields()
    if not any(f.get("id") == fid for f in items):
        raise ValueError("field not found")
    _save_fields(fid, items)
    reload()
    return public_config()


def delete_field(field_id: str) -> Dict[str, Any]:
    fid = str(field_id or "").strip()
    items = [f for f in fields() if f.get("id") != fid]
    new_active = active_field_id()
    if new_active == fid:
        new_active = items[0]["id"] if items else None
    _save_fields(new_active, items)
    reload()
    return public_config()


def set_disabled() -> Dict[str, Any]:
    _save_fields(None, [])
    reload()
    return public_config()

