"""Збереження полів оператора (config/field_runtime.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_PATH = _ROOT / "config" / "field_runtime.yaml"


def load_runtime() -> Optional[dict]:
    if not RUNTIME_PATH.is_file():
        return None
    with open(RUNTIME_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else None


def load_runtime_v2() -> dict:
    """Нормалізувати schema до v2: {version:2, active_field_id, fields:[...]}."""
    raw = load_runtime() or {}
    if not isinstance(raw, dict):
        return {"version": 2, "active_field_id": None, "fields": []}
    if raw.get("version") == 2 and isinstance(raw.get("fields"), list):
        return raw
    # legacy v1: {enabled, operator_set, polygon}
    poly = raw.get("polygon") or []
    fields = []
    if raw.get("enabled") and isinstance(poly, list) and len(poly) >= 3:
        fields = [
            {
                "id": "field_1",
                "name": "Field 1",
                "enabled": True,
                "polygon": poly,
                "created_from": "legacy_v1",
            }
        ]
        return {"version": 2, "active_field_id": "field_1", "fields": fields}
    return {"version": 2, "active_field_id": None, "fields": []}


def save_runtime(cfg: Dict[str, Any]) -> Dict[str, Any]:
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNTIME_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False)
    return cfg


def clear_runtime() -> None:
    if RUNTIME_PATH.is_file():
        RUNTIME_PATH.unlink()

