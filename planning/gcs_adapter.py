"""Адаптер планувальника → gcs_mission_v2."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from web.mission_record import MISSION_FORMAT_V2, default_record, normalize_record

PLANNING_SOURCE = "vineyard_rows_enu"


def infer_segments(waypoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Сегменти маршруту: transfer між рядами, row_gps вздовж ряду (CV на полі)."""
    segments: List[Dict[str, Any]] = []
    for i in range(len(waypoints) - 1):
        role_a = waypoints[i].get("role", "waypoint")
        role_b = waypoints[i + 1].get("role", "waypoint")
        if role_a == "turn" or role_b == "turn":
            seg_type = "transfer"
            note = "GPS міжряддя; увімкніть CV hybrid у ряду на полі"
        elif role_a in ("row_start", "row_mid") and role_b in ("row_mid", "row_end"):
            seg_type = "row_gps"
            note = "GPS вздовж ряду; точність ~1 m — RTK + CV hybrid"
        elif role_a == "row_end" and role_b == "row_start":
            seg_type = "transfer"
            note = "Перехід до наступного ряду"
        else:
            seg_type = "gps"
            note = ""
        seg: Dict[str, Any] = {
            "type": seg_type,
            "from_index": i,
            "to_index": i + 1,
        }
        if note:
            seg["note"] = note
        ri = waypoints[i].get("row_index")
        if ri is not None:
            seg["row_index"] = ri
        segments.append(seg)
    return segments


def build_planning_meta(
    *,
    origin_lat: float,
    origin_lon: float,
    azimuth_deg: float,
    row_spacing_m: float,
    row_length_m: float,
    row_count: int,
    use_zigzag: bool,
    densify_step_m: Optional[float],
) -> Dict[str, Any]:
    return {
        "source": PLANNING_SOURCE,
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "azimuth_deg": azimuth_deg,
        "row_spacing_m": row_spacing_m,
        "row_length_m": row_length_m,
        "row_count": row_count,
        "use_zigzag": use_zigzag,
        "densify_step_m": densify_step_m,
        "navigation_note": (
            "Міжряддя та повороти — GPS waypoints; "
            "точність ~1 m у ряду — RTK + CV hybrid (не щільний GPS кожен метр)."
        ),
    }


def waypoints_to_gcs_mission_v2(
    waypoints: List[Dict[str, Any]],
    vehicle_id: str,
    *,
    default_speed_m_s: float = 1.0,
    name: str = "",
    description: str = "",
    record: Optional[dict] = None,
    planning: Optional[dict] = None,
    include_roles: bool = True,
) -> dict:
    """Повний payload gcs_mission_v2 з опційними planning/segments."""
    rec = normalize_record(record or default_record())
    wp_out: List[Dict[str, Any]] = []
    for wp in waypoints:
        entry: Dict[str, Any] = {
            "lat": wp["lat"],
            "lon": wp["lon"],
        }
        if include_roles and wp.get("role"):
            entry["role"] = wp["role"]
        if include_roles and wp.get("row_index") is not None:
            entry["row_index"] = wp["row_index"]
        wp_out.append(entry)

    payload: Dict[str, Any] = {
        "format": MISSION_FORMAT_V2,
        "vehicle_id": vehicle_id,
        "name": name or "vineyard_rows",
        "description": description
        or "Згенеровано планувальником рядів (planning/)",
        "default_speed_m_s": float(default_speed_m_s),
        "work": {
            "started_at": rec.get("work_started_at"),
            "finished_at": rec.get("work_finished_at"),
        },
        "spraying": dict(rec.get("spraying") or {}),
        "field_notes": rec.get("field_notes") or "",
        "waypoints": wp_out,
    }
    if planning:
        payload["planning"] = planning
    if len(wp_out) >= 2:
        payload["segments"] = infer_segments(waypoints)
    return payload


def lines_to_gcs_mission_v2(
    waypoints: List[Dict[str, Any]],
    vehicle_id: str,
    planning: dict,
    **kwargs: Any,
) -> dict:
    return waypoints_to_gcs_mission_v2(
        waypoints, vehicle_id, planning=planning, **kwargs
    )
