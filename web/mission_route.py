"""Чернетка маршруту та фіксація реальних GPS після першого проходу ряду."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

COORD_DECIMALS = 7


def normalize_nav_wp(wp: dict) -> Dict[str, float]:
    return {
        "lat": round(float(wp["lat"]), COORD_DECIMALS),
        "lon": round(float(wp["lon"]), COORD_DECIMALS),
    }


def normalize_route_wp(wp: dict) -> Dict[str, Any]:
    out: Dict[str, Any] = normalize_nav_wp(wp)
    role = wp.get("role")
    if role is not None:
        out["role"] = str(role)
    if wp.get("row_index") is not None:
        out["row_index"] = int(wp["row_index"])
    return out


def is_first_row_end_index(index: int, waypoints: List[dict]) -> bool:
    """Чи прибуття на waypoint index — кінець першого ряду (для фіксації маршруту)."""
    if index < 0 or index >= len(waypoints):
        return False
    wp = waypoints[index]
    if wp.get("role") == "row_end":
        ri = wp.get("row_index")
        if ri is None:
            row_ends = [i for i, w in enumerate(waypoints) if w.get("role") == "row_end"]
            return bool(row_ends) and index == row_ends[0]
        return int(ri) == 0
    if not any(w.get("role") for w in waypoints):
        return index == 1 and len(waypoints) >= 2
    return False
