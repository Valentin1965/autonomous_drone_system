"""Планувальник: LineString (ENU м) → waypoints lat/lon для ground rover GCS."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

# MAVLink constants (опційно для експорту mission items; GCS використовує lat/lon)
MAV_FRAME_GLOBAL_INT = 5
MAV_FRAME_LOCAL_NED = 1
MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_NAV_TAKEOFF = 22

COORD_DECIMALS = 7

GROUND_ROVER_DEFAULTS = {
    "add_takeoff": False,
    "add_rtl": False,
    "use_zigzag": True,
    "add_turn_points": True,
    "turn_point_offset_m": 2.5,
    "densify_step_m": None,
    "altitude_m": 0.0,
}


@dataclass
class MissionItemInt:
    seq: int
    frame: int
    command: int
    current: int = 0
    autocontinue: int = 1
    param1: float = 0.0
    param2: float = 0.0
    param3: float = 0.0
    param4: float = 0.0
    x: int = 0
    y: int = 0
    z: float = 0.0


def _enu_to_latlon(
    east: float, north: float, origin_lat: float, origin_lon: float
) -> Tuple[float, float]:
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(origin_lat))
    lat = origin_lat + north / meters_per_deg_lat
    lon = origin_lon + east / meters_per_deg_lon
    return lat, lon


def _latlon_to_enu(
    lat: float, lon: float, origin_lat: float, origin_lon: float
) -> Tuple[float, float]:
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(origin_lat))
    north = (float(lat) - origin_lat) * meters_per_deg_lat
    east = (float(lon) - origin_lon) * meters_per_deg_lon
    return east, north


def polygon_latlon_to_enu(
    polygon: List[Dict[str, float]], origin_lat: float, origin_lon: float
) -> Polygon:
    if not polygon or len(polygon) < 3:
        raise ValueError("polygon requires >=3 points")
    pts = [_latlon_to_enu(p["lat"], p["lon"], origin_lat, origin_lon) for p in polygon]
    return Polygon(pts)


def _rotate_xy(e: float, n: float, ang_rad: float) -> Tuple[float, float]:
    ca = math.cos(ang_rad)
    sa = math.sin(ang_rad)
    return (e * ca - n * sa, e * sa + n * ca)


def field_polygon_to_row_lines(
    field_poly_enu: Polygon,
    *,
    azimuth_deg: float,
    row_spacing_m: float,
    extend_m: float = 10.0,
) -> List[LineString]:
    """
    Полігон поля (ENU м) → список рядків (ENU) обрізаних по полігону.

    azimuth_deg: напрямок ряду (0° = північ). Використовується як обертання системи.
    """
    if row_spacing_m <= 0:
        raise ValueError("row_spacing_m must be positive")
    if field_poly_enu.is_empty:
        return []

    # Обертаємо координати так, щоб ряд ішов по +Y (north), а міжряддя по X.
    ang = -math.radians(float(azimuth_deg))
    coords = list(field_poly_enu.exterior.coords)
    rot_coords = [_rotate_xy(e, n, ang) for (e, n) in coords]
    rot_poly = Polygon(rot_coords)
    minx, miny, maxx, maxy = rot_poly.bounds

    lines: List[LineString] = []
    x = minx
    # Щоб не пропустити край через float, стартуємо трохи лівіше
    x = minx - 1e-6
    while x <= maxx + 1e-6:
        base = LineString([(x, miny - extend_m), (x, maxy + extend_m)])
        seg = rot_poly.intersection(base)
        if seg.is_empty:
            x += row_spacing_m
            continue
        # seg може бути LineString або MultiLineString
        parts = []
        try:
            geoms = list(seg.geoms)  # type: ignore[attr-defined]
        except Exception:
            geoms = [seg]
        for g in geoms:
            if isinstance(g, LineString) and g.length > 0.5:
                parts.append(g)
        if parts:
            for p in parts:
                # повертаємо обертання назад
                back = [_rotate_xy(px, py, -ang) for (px, py) in p.coords]
                lines.append(LineString(back))
        x += row_spacing_m

    # Зібрати в один список, але зберегти порядок по X (міжряддя)
    # line.coords[0] беремо як репер
    lines.sort(key=lambda ln: ln.coords[0][0])
    return lines


def suggest_azimuth_deg_from_polygon(field_poly_enu: Polygon) -> float:
    """
    Автовибір азимута рядів по контуру: мінімальна площа rotated bbox.
    Повертає азимут ряду у градусах від півночі (0..180).
    """
    if field_poly_enu.is_empty:
        return 0.0
    rect = field_poly_enu.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    if len(coords) < 4:
        return 0.0
    # беремо найдовшу сторону прямокутника як напрямок ряду
    best = None
    best_len = -1.0
    for i in range(4):
        (x1, y1) = coords[i]
        (x2, y2) = coords[i + 1]
        dx, dy = (x2 - x1), (y2 - y1)
        ln = math.hypot(dx, dy)
        if ln > best_len:
            best_len = ln
            best = (dx, dy)
    if not best or best_len < 1e-6:
        return 0.0
    dx, dy = best
    # ENU: dx=east, dy=north. Азимут від півночі: atan2(east, north)
    az = math.degrees(math.atan2(dx, dy)) % 180.0
    return float(az)


def _latlon_dict(
    lat: float,
    lon: float,
    role: str = "waypoint",
    row_index: Optional[int] = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "lat": round(float(lat), COORD_DECIMALS),
        "lon": round(float(lon), COORD_DECIMALS),
        "role": role,
    }
    if row_index is not None:
        d["row_index"] = int(row_index)
    return d


def _line_endpoints(line: LineString) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    coords = list(line.coords)
    if len(coords) < 2:
        raise ValueError("LineString must have at least 2 points")
    return coords[0], coords[-1]


def _zigzag_order(lines: List[LineString]) -> List[LineString]:
    ordered: List[LineString] = []
    for i, line in enumerate(lines):
        coords = list(line.coords)
        if i % 2 == 0:
            ordered.append(LineString(coords))
        else:
            ordered.append(LineString(coords[::-1]))
    return ordered


def densify_line(line: LineString, step_m: float) -> LineString:
    """Інтерполяція точок вздовж лінії з кроком step_m (метри ENU)."""
    if step_m <= 0:
        raise ValueError("step_m must be positive")
    length = float(line.length)
    if length < 1e-6:
        return line
    n = max(1, int(math.ceil(length / step_m)))
    distances = [i * length / n for i in range(n + 1)]
    pts = [line.interpolate(d).coords[0] for d in distances]
    return LineString(pts)


def build_parallel_row_lines(
    row_count: int,
    row_length_m: float,
    row_spacing_m: float,
    azimuth_deg: float = 0.0,
    origin_east: float = 0.0,
    origin_north: float = 0.0,
) -> List[LineString]:
    """
    Паралельні ряди в локальній ENU (east, north), метри.

    azimuth_deg — напрямок ряду за годинниковою від півночі (0° = на північ).
    Ряди зміщуються перпендикулярно на row_spacing_m.
    """
    if row_count < 1:
        raise ValueError("row_count must be >= 1")
    if row_length_m <= 0:
        raise ValueError("row_length_m must be positive")
    if row_spacing_m <= 0:
        raise ValueError("row_spacing_m must be positive")

    h = math.radians(float(azimuth_deg))
    along_e = math.sin(h) * row_length_m
    along_n = math.cos(h) * row_length_m
    perp_e = math.cos(h) * row_spacing_m
    perp_n = -math.sin(h) * row_spacing_m

    lines: List[LineString] = []
    for i in range(row_count):
        base_e = origin_east + perp_e * i
        base_n = origin_north + perp_n * i
        end_e = base_e + along_e
        end_n = base_n + along_n
        lines.append(LineString([(base_e, base_n), (end_e, end_n)]))
    return lines


def lines_to_latlon_waypoints(
    lines: Union[LineString, Iterable[LineString]],
    origin_lat: float,
    origin_lon: float,
    *,
    use_zigzag: bool = True,
    add_turn_points: bool = True,
    turn_point_offset_m: float = 2.5,
    densify_step_m: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Лінії ENU → список waypoints для GCS / MissionRunner.

    За замовчуванням лише вхід/вихід ряду (+ turn між рядами).
    Точність ~1 m у середині ряду — RTK + CV hybrid на полі, не densify GPS.
    """
    if isinstance(lines, LineString):
        lines_list = [lines]
    else:
        lines_list = list(lines)
    if not lines_list:
        return []

    if use_zigzag:
        lines_list = _zigzag_order(lines_list)

    waypoints: List[Dict[str, Any]] = []
    prev_end: Optional[Tuple[float, float]] = None

    for row_idx, line in enumerate(lines_list):
        work_line = line
        if densify_step_m is not None and densify_step_m > 0:
            work_line = densify_line(line, densify_step_m)

        coords = list(work_line.coords)
        if len(coords) < 2:
            continue

        if densify_step_m is not None and densify_step_m > 0 and len(coords) > 2:
            for j, (e, n) in enumerate(coords):
                if j == 0:
                    role = "row_start"
                elif j == len(coords) - 1:
                    role = "row_end"
                else:
                    role = "row_mid"
                lat, lon = _enu_to_latlon(e, n, origin_lat, origin_lon)
                waypoints.append(_latlon_dict(lat, lon, role=role, row_index=row_idx))
            prev_end = coords[-1]
            continue

        start, end = _line_endpoints(work_line)
        pts: List[Tuple[Tuple[float, float], str]] = [
            (start, "row_start"),
            (end, "row_end"),
        ]

        if add_turn_points and prev_end is not None and turn_point_offset_m > 0:
            sx, sy = start
            px, py = prev_end
            dir1 = (sx - px, sy - py)
            n = math.hypot(dir1[0], dir1[1])
            if n > 1e-6:
                ux, uy = dir1[0] / n, dir1[1] / n
                turn = (
                    sx - ux * turn_point_offset_m,
                    sy - uy * turn_point_offset_m,
                )
                pts = [(turn, "turn"), (start, "row_start"), (end, "row_end")]

        for p, role in pts:
            lat, lon = _enu_to_latlon(p[0], p[1], origin_lat, origin_lon)
            waypoints.append(_latlon_dict(lat, lon, role=role, row_index=row_idx))

        prev_end = end

    return waypoints


def lines_to_mission_items(
    lines: Union[LineString, Iterable[LineString]],
    frame: int = MAV_FRAME_GLOBAL_INT,
    origin_lat: Optional[float] = None,
    origin_lon: Optional[float] = None,
    altitude: float = 0.0,
    add_takeoff: bool = False,
    add_rtl: bool = False,
    use_zigzag: bool = True,
    add_turn_points: bool = True,
    turn_point_offset: float = 2.5,
) -> List[MissionItemInt]:
    """MAVLink mission items (опційно); ground rover: takeoff/rtl вимкнено."""
    wps = lines_to_latlon_waypoints(
        lines,
        float(origin_lat or 0),
        float(origin_lon or 0),
        use_zigzag=use_zigzag,
        add_turn_points=add_turn_points,
        turn_point_offset_m=turn_point_offset,
    )
    mission: List[MissionItemInt] = []
    seq = 0

    if add_takeoff:
        if origin_lat is None or origin_lon is None:
            raise ValueError("origin_lat and origin_lon required")
        mission.append(
            MissionItemInt(
                seq=seq,
                frame=frame,
                command=MAV_CMD_NAV_TAKEOFF,
                current=1,
                x=int(round(origin_lat * 1e7)),
                y=int(round(origin_lon * 1e7)),
                z=altitude,
            )
        )
        seq += 1

    for wp in wps:
        lat, lon = wp["lat"], wp["lon"]
        if frame == MAV_FRAME_GLOBAL_INT:
            x, y = int(round(lat * 1e7)), int(round(lon * 1e7))
        else:
            raise ValueError("LOCAL_NED export via mission items not supported; use lat/lon")
        mission.append(
            MissionItemInt(
                seq=seq,
                frame=frame,
                command=MAV_CMD_NAV_WAYPOINT,
                x=x,
                y=y,
                z=altitude,
            )
        )
        seq += 1

    if add_rtl:
        if origin_lat is None or origin_lon is None:
            raise ValueError("origin_lat and origin_lon required")
        mission.append(
            MissionItemInt(
                seq=seq,
                frame=frame,
                command=MAV_CMD_NAV_RETURN_TO_LAUNCH,
                x=int(round(origin_lat * 1e7)),
                y=int(round(origin_lon * 1e7)),
                z=altitude,
            )
        )
    return mission


def mission_items_to_json(mission_items: List[MissionItemInt], indent: int = 2) -> str:
    return json.dumps([asdict(mi) for mi in mission_items], ensure_ascii=False, indent=indent)


def strip_roles(waypoints: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    """Лише lat/lon для MissionRunner."""
    return [{"lat": wp["lat"], "lon": wp["lon"]} for wp in waypoints if "lat" in wp and "lon" in wp]
