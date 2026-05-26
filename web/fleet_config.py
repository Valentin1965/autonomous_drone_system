"""Збереження складу флоту (кількість дронів) між сесіями."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_PATH = _ROOT / "config" / "fleet_runtime.yaml"
_COLORS = ("#ff9800", "#4caf50", "#2196f3", "#e91e63", "#9c27b0", "#00bcd4")
MAX_FLEET = 6
MIN_FLEET = 1


def load_runtime_fleet() -> Optional[dict]:
    if not RUNTIME_PATH.is_file():
        return None
    with open(RUNTIME_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_runtime_fleet(count: int, vehicles: List[dict], default_vehicle: str) -> None:
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "enabled": True,
        "count": count,
        "default_vehicle": default_vehicle,
        "vehicles": vehicles,
    }
    with open(RUNTIME_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)


def build_vehicle_entries(count: int, system_cfg: dict) -> List[dict]:
    """Згенерувати rover_1..N з унікальними портами для симуляції."""
    count = max(MIN_FLEET, min(MAX_FLEET, int(count)))
    mavlink = system_cfg.get("mavlink", {})
    base_conn = mavlink.get("connection_sim") or "udp:127.0.0.1:14550"
    base_port = 14550
    if ":" in base_conn:
        try:
            base_port = int(base_conn.rsplit(":", 1)[-1])
        except ValueError:
            pass
    entries = []
    for i in range(count):
        port = base_port + i
        entries.append({
            "id": f"rover_{i + 1}",
            "name": f"Rover {i + 1}",
            "color": _COLORS[i % len(_COLORS)],
            "mavlink_connection": f"udp:127.0.0.1:{port}",
            "sim_bind": f"udpin:0.0.0.0:{port}",
            "start_lat": 50.4501 + i * 0.0004,
            "start_lon": 30.5234 + i * 0.0004,
        })
    return entries


def merge_fleet_config(system_cfg: dict) -> dict:
    """Пріоритет: fleet_runtime.yaml → system.yaml fleet."""
    runtime = load_runtime_fleet()
    fleet = dict(system_cfg.get("fleet") or {})
    if runtime and runtime.get("vehicles"):
        fleet["enabled"] = True
        fleet["vehicles"] = runtime["vehicles"]
        fleet["default_vehicle"] = runtime.get(
            "default_vehicle", fleet.get("default_vehicle", "rover_1")
        )
        fleet["count"] = runtime.get("count", len(runtime["vehicles"]))
    return fleet
