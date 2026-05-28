"""Збереження складу флоту (кількість дронів) між сесіями."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_PATH = _ROOT / "config" / "fleet_runtime.yaml"
_COLORS = ("#ff9800", "#4caf50", "#2196f3", "#e91e63", "#9c27b0", "#00bcd4")
FLEET_POOL_SIZE = 6
MAX_FLEET = FLEET_POOL_SIZE
MIN_FLEET = 1


def _default_lat(index: int = 0) -> float:
    from config.geo_defaults import DEFAULT_LAT, FLEET_POSITION_STEP

    return DEFAULT_LAT + index * FLEET_POSITION_STEP


def _default_lon(index: int = 0) -> float:
    from config.geo_defaults import DEFAULT_LON, FLEET_POSITION_STEP

    return DEFAULT_LON + index * FLEET_POSITION_STEP


# Dev/sim: окреме відео на кожен rover (імітація камери без заліза)
_FLEET_VIDEO_FILES = (
    "assets/videos/vineyard_demo.mp4",
    "assets/videos/vineyard_demo1.mp4",
    "assets/videos/vineyard_demo2.mp4",
    "assets/videos/vineyard_demo3.mp4",
    "assets/videos/vineyard_demo4.mp4",
    "assets/videos/vineyard_demo5.mp4",
)


def default_fleet_video_file(index: int) -> str:
    """index: 0-based rover index → шлях до відео в assets/videos/."""
    if 0 <= index < len(_FLEET_VIDEO_FILES):
        return _FLEET_VIDEO_FILES[index]
    return _FLEET_VIDEO_FILES[-1]


def load_runtime_fleet() -> Optional[dict]:
    if not RUNTIME_PATH.is_file():
        return None
    with open(RUNTIME_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_runtime_fleet(
    vehicles: List[dict],
    default_vehicle: str,
    active_vehicle_ids: List[str],
) -> None:
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "enabled": True,
        "pool_size": FLEET_POOL_SIZE,
        "count": len(active_vehicle_ids),
        "active_vehicle_ids": list(active_vehicle_ids),
        "default_vehicle": default_vehicle,
        "vehicles": vehicles,
    }
    with open(RUNTIME_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)


def _default_vehicle_entry(index: int, system_cfg: dict) -> dict:
    mavlink = system_cfg.get("mavlink", {})
    base_conn = mavlink.get("connection_sim") or "udp:127.0.0.1:14550"
    base_port = 14550
    if ":" in base_conn:
        try:
            base_port = int(base_conn.rsplit(":", 1)[-1])
        except ValueError:
            pass
    port = base_port + index
    return {
        "id": f"rover_{index + 1}",
        "name": f"Rover {index + 1}",
        "color": _COLORS[index % len(_COLORS)],
        "mavlink_connection": f"udp:127.0.0.1:{port}",
        "sim_bind": f"udpin:0.0.0.0:{port}",
        "start_lat": _default_lat(index),
        "start_lon": _default_lon(index),
        "video_file": default_fleet_video_file(index),
    }


def build_pool_entries(system_cfg: dict) -> List[dict]:
    """Повний roster станції — завжди FLEET_POOL_SIZE дронів."""
    fleet_cfg = system_cfg.get("fleet") or {}
    existing = {
        str(v.get("id")): dict(v)
        for v in (fleet_cfg.get("vehicles") or [])
        if v.get("id")
    }
    entries = []
    for i in range(FLEET_POOL_SIZE):
        vid = f"rover_{i + 1}"
        ent = existing.get(vid) or _default_vehicle_entry(i, system_cfg)
        ent["id"] = vid
        ent.setdefault("name", f"Rover {i + 1}")
        ent.setdefault("color", _COLORS[i % len(_COLORS)])
        ent.setdefault("video_file", default_fleet_video_file(i))
        entries.append(ent)
    return entries


def build_vehicle_entries(count: int, system_cfg: dict) -> List[dict]:
    """Зворотна сумісність: повний пул + active_vehicle_ids у runtime."""
    return build_pool_entries(system_cfg)


def active_ids_for_count(count: int) -> List[str]:
    n = max(MIN_FLEET, min(FLEET_POOL_SIZE, int(count)))
    return [f"rover_{i + 1}" for i in range(n)]


def resolve_active_ids(fleet_cfg: dict, pool: List[dict]) -> List[str]:
    """Які дрони в роботі: runtime active_vehicle_ids → count → перші 2."""
    raw = fleet_cfg.get("active_vehicle_ids")
    if raw:
        pool_ids = {str(v.get("id")) for v in pool}
        return [str(vid) for vid in raw if str(vid) in pool_ids]
    count = fleet_cfg.get("count")
    if count is not None:
        return active_ids_for_count(int(count))
    flagged = [str(v.get("id")) for v in pool if v.get("active")]
    if flagged:
        return flagged
    return active_ids_for_count(2)


def merge_fleet_config(system_cfg: dict) -> dict:
    """Пріоритет: fleet_runtime.yaml → system.yaml fleet. Пул завжди 6 дронів."""
    runtime = load_runtime_fleet()
    fleet = dict(system_cfg.get("fleet") or {})
    pool = build_pool_entries(system_cfg)
    fleet["enabled"] = bool(fleet.get("enabled", True))
    fleet["pool_size"] = FLEET_POOL_SIZE
    fleet["vehicles"] = pool
    if runtime:
        fleet["default_vehicle"] = runtime.get(
            "default_vehicle", fleet.get("default_vehicle", "rover_1")
        )
        fleet["active_vehicle_ids"] = runtime.get("active_vehicle_ids")
        fleet["count"] = runtime.get("count")
        rt_map = {str(v.get("id")): v for v in (runtime.get("vehicles") or []) if v.get("id")}
        merged = []
        for ent in pool:
            vid = str(ent["id"])
            if vid in rt_map:
                merged.append({**ent, **rt_map[vid], "id": vid})
            else:
                merged.append(ent)
        fleet["vehicles"] = merged
    fleet["active_vehicle_ids"] = resolve_active_ids(fleet, fleet["vehicles"])
    fleet["count"] = len(fleet["active_vehicle_ids"])
    return fleet
