"""
Конфігурація сервера аналізу.
Читає config/server.yaml (якщо є) або змінні середовища.
Може запускатись без будь-яких залежностей від GCS/station.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CACHE: Optional[Dict[str, Any]] = None


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def load() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    path = _ROOT / "config" / "server.yaml"
    cfg: Dict[str, Any] = {}
    if path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    _CACHE = cfg
    return _CACHE


def db_path() -> Path:
    cfg = load()
    rel = cfg.get("db", "data/monitoring/server/fleet.db")
    p = Path(rel)
    return p if p.is_absolute() else _ROOT / p


def captures_dir() -> Path:
    cfg = load()
    rel = cfg.get("captures_dir", "data/monitoring/server_captures")
    p = Path(rel)
    return p if p.is_absolute() else _ROOT / p


def api_key() -> str:
    cfg = load()
    return str(cfg.get("api_key") or _env("MONITORING_API_KEY", "")).strip()


def yolo_device() -> str:
    cfg = load()
    return str(cfg.get("device") or _env("YOLO_DEVICE", "cpu")).strip().lower()


def yolo_confidence() -> float:
    cfg = load()
    try:
        return float(cfg.get("confidence") or _env("YOLO_CONF", "0.45"))
    except (ValueError, TypeError):
        return 0.45


def model_weights() -> Dict[str, str]:
    """Повертає {crop: шлях} з конфіга або env."""
    cfg = load()
    models = dict(cfg.get("models") or {})
    for env_key, crop in (
        ("MONITORING_DEFAULT_WEIGHTS", "default"),
        ("MONITORING_VINEYARD_WEIGHTS", "vineyard"),
        ("MONITORING_BANANA_WEIGHTS", "banana"),
    ):
        v = _env(env_key)
        if v:
            models.setdefault(crop, v)
    return models
