"""Збереження геозони оператора (config/geofence_runtime.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_PATH = _ROOT / "config" / "geofence_runtime.yaml"


def load_runtime() -> Optional[dict]:
    if not RUNTIME_PATH.is_file():
        return None
    with open(RUNTIME_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else None


def save_runtime(cfg: Dict[str, Any]) -> Dict[str, Any]:
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNTIME_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, default_flow_style=False)
    return cfg


def clear_runtime() -> None:
    if RUNTIME_PATH.is_file():
        RUNTIME_PATH.unlink()
