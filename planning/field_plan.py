"""Високорівневе планування поля виноградника → gcs_mission_v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from planning.gcs_adapter import build_planning_meta, waypoints_to_gcs_mission_v2
from planning.mission_waypoints import (
    GROUND_ROVER_DEFAULTS,
    build_parallel_row_lines,
    field_polygon_to_row_lines,
    lines_to_latlon_waypoints,
    polygon_latlon_to_enu,
    suggest_azimuth_deg_from_polygon,
    strip_roles,
)


@dataclass
class FieldPlanRequest:
    origin_lat: float
    origin_lon: float
    azimuth_deg: float = 0.0
    auto_azimuth: bool = False
    row_spacing_m: float = 1.0
    row_length_m: float = 50.0
    row_count: int = 5
    origin_east_m: float = 0.0
    origin_north_m: float = 0.0
    use_zigzag: bool = True
    add_turn_points: bool = True
    turn_point_offset_m: float = 2.5
    densify_step_m: Optional[float] = None
    vehicle_id: str = "rover_1"
    default_speed_m_s: float = 1.0
    name: str = ""
    description: str = ""
    field_notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "FieldPlanRequest":
        d = dict(data)
        return cls(
            origin_lat=float(d["origin_lat"]),
            origin_lon=float(d["origin_lon"]),
            azimuth_deg=float(d.get("azimuth_deg", 0.0)),
            auto_azimuth=bool(d.get("auto_azimuth", False)),
            row_spacing_m=float(d.get("row_spacing_m", 1.0)),
            row_length_m=float(d.get("row_length_m", 50.0)),
            row_count=int(d.get("row_count", 5)),
            origin_east_m=float(d.get("origin_east_m", 0.0)),
            origin_north_m=float(d.get("origin_north_m", 0.0)),
            use_zigzag=bool(d.get("use_zigzag", True)),
            add_turn_points=bool(d.get("add_turn_points", True)),
            turn_point_offset_m=float(
                d.get("turn_point_offset_m", GROUND_ROVER_DEFAULTS["turn_point_offset_m"])
            ),
            densify_step_m=d.get("densify_step_m"),
            vehicle_id=str(d.get("vehicle_id", "rover_1")),
            default_speed_m_s=float(d.get("default_speed_m_s", 1.0)),
            name=str(d.get("name", "")),
            description=str(d.get("description", "")),
            field_notes=str(d.get("field_notes", "")),
        )


def plan_vineyard_field(req: FieldPlanRequest) -> Dict[str, Any]:
    """
    Побудувати маршрут zigzag по паралельних рядах.

    Повертає dict з keys: waypoints (з role), gcs_mission, planning, segments, stats.
    """
    if req.row_count < 1 or req.row_count > 500:
        raise ValueError("row_count must be 1..500")
    if req.row_spacing_m <= 0 or req.row_spacing_m > 50:
        raise ValueError("row_spacing_m must be in (0, 50]")
    if req.row_length_m <= 0 or req.row_length_m > 5000:
        raise ValueError("row_length_m must be in (0, 5000]")

    densify = req.densify_step_m
    if densify is not None:
        try:
            densify = float(densify)
            if densify <= 0:
                densify = None
        except (TypeError, ValueError):
            densify = None

    lines = build_parallel_row_lines(
        row_count=req.row_count,
        row_length_m=req.row_length_m,
        row_spacing_m=req.row_spacing_m,
        azimuth_deg=req.azimuth_deg,
        origin_east=req.origin_east_m,
        origin_north=req.origin_north_m,
    )
    waypoints = lines_to_latlon_waypoints(
        lines,
        req.origin_lat,
        req.origin_lon,
        use_zigzag=req.use_zigzag,
        add_turn_points=req.add_turn_points,
        turn_point_offset_m=req.turn_point_offset_m,
        densify_step_m=densify,
    )
    if not waypoints:
        raise ValueError("no waypoints generated")

    planning = build_planning_meta(
        origin_lat=req.origin_lat,
        origin_lon=req.origin_lon,
        azimuth_deg=req.azimuth_deg,
        row_spacing_m=req.row_spacing_m,
        row_length_m=req.row_length_m,
        row_count=req.row_count,
        use_zigzag=req.use_zigzag,
        densify_step_m=densify,
    )
    record = {"field_notes": req.field_notes} if req.field_notes else None
    gcs = waypoints_to_gcs_mission_v2(
        waypoints,
        req.vehicle_id,
        default_speed_m_s=req.default_speed_m_s,
        name=req.name,
        description=req.description,
        record=record,
        planning=planning,
    )

    return {
        "waypoints": waypoints,
        "waypoints_nav": strip_roles(waypoints),
        "gcs_mission": gcs,
        "planning": planning,
        "segments": gcs.get("segments", []),
        "stats": {
            "row_count": req.row_count,
            "waypoint_count": len(waypoints),
            "row_spacing_m": req.row_spacing_m,
            "row_length_m": req.row_length_m,
        },
    }


def plan_field_from_polygon(req: FieldPlanRequest, polygon_latlon: List[dict]) -> Dict[str, Any]:
    """Планування рядів всередині складного контуру поля (полігон)."""
    densify = req.densify_step_m
    if densify is not None:
        try:
            densify = float(densify)
            if densify <= 0:
                densify = None
        except (TypeError, ValueError):
            densify = None

    poly_enu = polygon_latlon_to_enu(polygon_latlon, req.origin_lat, req.origin_lon)
    if poly_enu.is_empty:
        raise ValueError("empty field polygon")

    if getattr(req, "azimuth_deg", 0.0) is None:
        req.azimuth_deg = 0.0
    # якщо оператор не задав azimuth або ввімкнув auto_azimuth
    auto_az = bool(getattr(req, "auto_azimuth", False))
    if auto_az or abs(float(req.azimuth_deg)) < 1e-9:
        req.azimuth_deg = suggest_azimuth_deg_from_polygon(poly_enu)

    lines = field_polygon_to_row_lines(
        poly_enu,
        azimuth_deg=req.azimuth_deg,
        row_spacing_m=req.row_spacing_m,
        extend_m=10.0,
    )
    if not lines:
        raise ValueError("no row lines for polygon (check spacing/azimuth)")

    waypoints = lines_to_latlon_waypoints(
        lines,
        req.origin_lat,
        req.origin_lon,
        use_zigzag=req.use_zigzag,
        add_turn_points=req.add_turn_points,
        turn_point_offset_m=req.turn_point_offset_m,
        densify_step_m=densify,
    )
    if not waypoints:
        raise ValueError("no waypoints generated")

    planning = build_planning_meta(
        origin_lat=req.origin_lat,
        origin_lon=req.origin_lon,
        azimuth_deg=req.azimuth_deg,
        row_spacing_m=req.row_spacing_m,
        row_length_m=req.row_length_m,
        row_count=req.row_count,
        use_zigzag=req.use_zigzag,
        densify_step_m=densify,
    )
    planning["field_polygon_points"] = len(polygon_latlon)
    planning["field_shape"] = "polygon"

    record = {"field_notes": req.field_notes} if req.field_notes else None
    gcs = waypoints_to_gcs_mission_v2(
        waypoints,
        req.vehicle_id,
        default_speed_m_s=req.default_speed_m_s,
        name=req.name or "vineyard_field_polygon",
        description=req.description
        or "Згенеровано по контуру поля (polygon) + ряди",
        record=record,
        planning=planning,
    )

    return {
        "waypoints": waypoints,
        "waypoints_nav": strip_roles(waypoints),
        "gcs_mission": gcs,
        "planning": planning,
        "segments": gcs.get("segments", []),
        "stats": {
            "row_count": None,
            "waypoint_count": len(waypoints),
            "row_spacing_m": req.row_spacing_m,
            "row_length_m": None,
        },
    }
