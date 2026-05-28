"""Станція / оператор — runtime поверх config/monitoring.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from monitoring.config_loader import _root, load_monitoring_config


def runtime_path() -> Path:
    return _root() / "config" / "monitoring_runtime.yaml"


def load_runtime_station() -> Dict[str, str]:
    path = runtime_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        st = data.get("station") or {}
        return {
            "id": str(st.get("id", "")).strip(),
            "operator": str(st.get("operator", "")).strip(),
        }
    except Exception:
        return {}


def save_runtime_station(*, station_id: str, operator: str) -> Dict[str, str]:
    path = runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {}
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
    data["station"] = {
        "id": station_id.strip() or "gcs-1",
        "operator": operator.strip(),
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    from monitoring import config_loader

    config_loader._CACHE = None
    return station_meta()


def station_meta() -> Dict[str, str]:
    """Після merge у load_monitoring_config — id/operator для uplink."""
    cfg = load_monitoring_config()
    st = cfg.get("station") or {}
    sid = str(st.get("id", "gcs-1")).strip() or "gcs-1"
    op = str(st.get("operator", "") or "").strip()
    return {"station_id": sid, "operator": op, "id": sid}
