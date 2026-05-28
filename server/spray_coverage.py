"""
Агрегація spray ↔ моніторинг з fleet_events (sprayer_on/off + payload).

Оброблена площа: path_length_m × swath_width_m з payload.spray_coverage
або оцінка за GPS між on/off, якщо payload відсутній.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from server import database as db

Point = Tuple[float, float]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _path_from_gps(points: List[Point]) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        total += _haversine_m(a[0], a[1], b[0], b[1])
    return total


def _parse_payload(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw) or {}
        except json.JSONDecodeError:
            return {}
    return {}


def _events_for_coverage(
    *,
    station_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    limit: int = 500,
) -> List[dict]:
    """Події sprayer + monitoring_capture для аналізу."""
    spray = db.list_operations(
        station_id=station_id,
        vehicle_id=vehicle_id,
        event_type=None,
        limit=limit,
    )
    out = []
    for row in spray:
        et = row.get("event_type") or ""
        if et in (
            "sprayer_on",
            "sprayer_off",
            "monitoring_capture",
            "monitoring_survey_start",
            "monitoring_survey_end",
        ):
            out.append(row)
    out.sort(key=lambda r: float(r.get("ts") or 0))
    return out


def build_spray_sessions(
    events: List[dict],
    *,
    default_swath_m: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Пари sprayer_on → sprayer_off; метрики з payload.spray_coverage або GPS.
    """
    sessions: List[Dict[str, Any]] = []
    open_sess: Optional[Dict[str, Any]] = None

    for ev in events:
        et = ev.get("event_type") or ""
        payload = _parse_payload(ev.get("payload"))
        vc = payload.get("vehicle_context") or {}
        sc = payload.get("spray_coverage") or vc.get("spray_coverage") or {}

        if et == "sprayer_on":
            lat, lon = ev.get("lat"), ev.get("lon")
            open_sess = {
                "vehicle_id": ev.get("vehicle_id") or "",
                "station_id": ev.get("station_id") or "",
                "operator": ev.get("operator") or "",
                "started_ts": float(ev.get("ts") or 0),
                "started_time": ev.get("time"),
                "start_lat": lat,
                "start_lon": lon,
                "gps_points": [],
                "source": payload.get("spray_source") or sc.get("source") or "",
            }
            if lat is not None and lon is not None:
                open_sess["gps_points"].append((float(lat), float(lon)))
            continue

        if et == "sprayer_off" and open_sess:
            if ev.get("lat") is not None and ev.get("lon") is not None:
                open_sess["gps_points"].append(
                    (float(ev["lat"]), float(ev["lon"]))
                )
            ended_ts = float(ev.get("ts") or 0)
            if sc:
                sess = {
                    **open_sess,
                    "session_id": sc.get("session_id"),
                    "ended_ts": ended_ts,
                    "ended_time": ev.get("time"),
                    "duration_s": sc.get("duration_s"),
                    "path_length_m": sc.get("path_length_m"),
                    "area_m2": sc.get("area_m2"),
                    "area_ha": sc.get("area_ha"),
                    "swath_width_m": sc.get("swath_width_m", default_swath_m),
                    "point_count": sc.get("point_count"),
                    "from_payload": True,
                }
            else:
                pts = open_sess["gps_points"]
                length_m = _path_from_gps(pts)
                swath = default_swath_m
                area_m2 = length_m * swath
                sess = {
                    **open_sess,
                    "ended_ts": ended_ts,
                    "ended_time": ev.get("time"),
                    "duration_s": round(max(0.0, ended_ts - open_sess["started_ts"]), 1),
                    "path_length_m": round(length_m, 2),
                    "area_m2": round(area_m2, 2),
                    "area_ha": round(area_m2 / 10_000.0, 4),
                    "swath_width_m": swath,
                    "point_count": len(pts),
                    "from_payload": False,
                }
            sessions.append(sess)
            open_sess = None
            continue

        if open_sess and et == "monitoring_capture":
            lat, lon = ev.get("lat"), ev.get("lon")
            if lat is not None and lon is not None:
                open_sess["gps_points"].append((float(lat), float(lon)))

    return sessions


def correlate_findings(
    findings: List[dict],
    sessions: List[dict],
    *,
    radius_m: float = 30.0,
) -> List[dict]:
    """Позначити знахідки, зняті під час/поруч із сесією оприскування."""
    out = []
    for f in findings:
        flat, flon = float(f.get("lat") or 0), float(f.get("lon") or 0)
        f_ts = None
        created = f.get("created_at") or ""
        spray_session = None
        during_spray = False
        for s in sessions:
            if s.get("vehicle_id") and f.get("vehicle_id"):
                if s["vehicle_id"] != f["vehicle_id"]:
                    continue
            start = float(s.get("started_ts") or 0)
            end = float(s.get("ended_ts") or start)
            # час зйомки з capture ts якщо є — інакше пропускаємо часовий зв'язок
            near = False
            if flat and flon and s.get("start_lat") is not None:
                for pt in s.get("gps_points") or [(s.get("start_lat"), s.get("start_lon"))]:
                    if pt and _haversine_m(flat, flon, pt[0], pt[1]) <= radius_m:
                        near = True
                        break
            if near:
                spray_session = s.get("session_id") or f"{s.get('started_time')}"
                during_spray = True
                break
        row = dict(f)
        row["spray_correlation"] = {
            "during_spray": during_spray,
            "session_ref": spray_session,
        }
        out.append(row)
    return out


def coverage_summary(
    *,
    station_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    limit: int = 500,
    default_swath_m: float = 2.0,
) -> Dict[str, Any]:
    events = _events_for_coverage(
        station_id=station_id, vehicle_id=vehicle_id, limit=limit
    )
    sessions = build_spray_sessions(events, default_swath_m=default_swath_m)
    total_length = sum(float(s.get("path_length_m") or 0) for s in sessions)
    total_area = sum(float(s.get("area_m2") or 0) for s in sessions)
    findings = db.list_findings(
        station_id=station_id,
        vehicle_id=vehicle_id,
        limit=min(limit, 200),
    )
    findings_linked = correlate_findings(findings, sessions)
    captures_during = sum(
        1 for e in events if e.get("event_type") == "monitoring_capture"
    )
    return {
        "session_count": len(sessions),
        "total_path_length_m": round(total_length, 2),
        "total_area_m2": round(total_area, 2),
        "total_area_ha": round(total_area / 10_000.0, 4),
        "sessions": sessions,
        "findings_count": len(findings),
        "findings_with_spray_context": sum(
            1
            for f in findings_linked
            if (f.get("spray_correlation") or {}).get("during_spray")
        ),
        "monitoring_captures_in_log": captures_during,
    }
