"""Завантаження config/monitoring.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

_CACHE: Dict[str, Any] | None = None


def _root() -> Path:
    try:
        from config.config_paths import project_root

        return project_root()
    except ImportError:
        return Path(__file__).resolve().parent.parent


def monitoring_config_path() -> Path:
    import os

    rel = os.environ.get("MONITORING_CONFIG", "").strip()
    if rel:
        p = Path(rel)
        return p if p.is_absolute() else _root() / p
    return _root() / "config" / "monitoring.yaml"


def load_monitoring_config(reload: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not reload:
        return _CACHE
    path = monitoring_config_path()
    if not path.is_file():
        _CACHE = {}
        return _CACHE
    with open(path, "r", encoding="utf-8") as f:
        _CACHE = yaml.safe_load(f) or {}
    _merge_runtime_station(_CACHE)
    return _CACHE


def _merge_runtime_station(cfg: Dict[str, Any]) -> None:
    """Підмішати config/monitoring_runtime.yaml (станція / оператор)."""
    from monitoring.station_config import runtime_path

    rt_path = runtime_path()
    if not rt_path.is_file():
        return
    try:
        with open(rt_path, "r", encoding="utf-8") as f:
            rt = yaml.safe_load(f) or {}
        st = rt.get("station")
        if isinstance(st, dict) and st:
            merged = dict(cfg.get("station") or {})
            merged.update({k: v for k, v in st.items() if v is not None})
            cfg["station"] = merged
    except Exception:
        pass


def findings_path() -> Path:
    cfg = load_monitoring_config()
    rel = (cfg.get("storage") or {}).get("findings_file", "data/monitoring/findings.json")
    p = Path(rel)
    return p if p.is_absolute() else _root() / p
