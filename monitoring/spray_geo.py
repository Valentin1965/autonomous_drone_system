"""Геометрія треку оприскування (GPS → довжина / площа смуги)."""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Відстань між двома WGS84 точками, метри."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def path_length_m(points: Sequence[Point]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        a = points[i - 1]
        b = points[i]
        total += haversine_m(a[0], a[1], b[0], b[1])
    return total


def area_from_path_m2(path_length_m: float, swath_width_m: float) -> float:
    """Оцінка обробленої площі: довжина треку × ширина смуги оприскувача."""
    if path_length_m <= 0 or swath_width_m <= 0:
        return 0.0
    return path_length_m * swath_width_m


def valid_gps(lat: float, lon: float) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return abs(lat) > 1e-4 or abs(lon) > 1e-4


def iter_path_chunks(
    points: Sequence[Point], min_dist_m: float
) -> Iterable[Point]:
    """Залишити точки з мінімальним кроком (зменшити шум GPS)."""
    if not points:
        return
    last: Point | None = None
    for lat, lon in points:
        if not valid_gps(lat, lon):
            continue
        if last is None:
            yield (lat, lon)
            last = (lat, lon)
            continue
        if haversine_m(last[0], last[1], lat, lon) >= min_dist_m:
            yield (lat, lon)
            last = (lat, lon)


def decimate_points(points: List[Point], min_dist_m: float) -> List[Point]:
    return list(iter_path_chunks(points, min_dist_m))
