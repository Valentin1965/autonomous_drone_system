"""Завантаження демо-маршруту з JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_demo_mission(path: Optional[str] = None) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    if path is None:
        from web.state import drone_state

        cfg = drone_state.load_config()
        path = cfg.get("simulator", {}).get("demo_mission", "config/demo_mission.json")

    p = Path(path)
    if not p.is_file():
        root = Path(__file__).resolve().parent.parent
        p = root / path
    if not p.is_file():
        raise FileNotFoundError(f"Demo mission not found: {path}")

    data = json.loads(p.read_text(encoding="utf-8"))
    wps = []
    for wp in data.get("waypoints", []):
        if wp.get("lat") is None or wp.get("lon") is None:
            continue
        wps.append({"lat": float(wp["lat"]), "lon": float(wp["lon"])})
    return wps, data


def apply_demo_to_state(path: Optional[str] = None, vehicle_id: Optional[str] = None) -> dict:
    from web.fleet import get_fleet

    wps, meta = load_demo_mission(path)
    v = get_fleet().get_vehicle(vehicle_id)
    v.mission_waypoints = list(wps)
    return {
        "vehicle_id": v.id,
        "count": len(wps),
        "name": meta.get("name"),
        "default_speed_m_s": meta.get("default_speed_m_s"),
        "waypoints": wps,
    }
