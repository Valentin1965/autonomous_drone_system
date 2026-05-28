"""
Зв'язок spray ↔ моніторинг: GPS-трек під час sprayer_active.

На sprayer_off у payload додається spray_coverage (довжина, площа, час).
Контекст зйомки моніторингу містить поточний стан оприскування.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from monitoring.config_loader import load_monitoring_config
from monitoring.spray_geo import (
    area_from_path_m2,
    decimate_points,
    path_length_m,
    valid_gps,
)

_lock = threading.Lock()
_active: Dict[str, "_Session"] = {}
_totals: Dict[str, Dict[str, float]] = {}


@dataclass
class _Session:
    vehicle_id: str
    session_id: str
    started_at: float
    source: str = "manual"
    points: List[Tuple[float, float]] = field(default_factory=list)


def _cfg() -> dict:
    cfg = load_monitoring_config()
    return cfg.get("spray_coverage") or {}


def _swath_width_m() -> float:
    return float(_cfg().get("swath_width_m", 2.0))


def _min_sample_dist_m() -> float:
    return float(_cfg().get("sample_min_dist_m", 0.5))


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _gps_for_vehicle(vehicle) -> Tuple[Optional[float], Optional[float]]:
    try:
        from simulator import fleet_registry

        pos = fleet_registry.get_position(vehicle.id)
        if pos and valid_gps(pos["lat"], pos["lon"]):
            return float(pos["lat"]), float(pos["lon"])
    except Exception:
        pass
    try:
        gps = vehicle.get_controller().get_status().get("gps") or {}
        lat, lon = gps.get("lat"), gps.get("lon")
        if lat is not None and lon is not None and valid_gps(lat, lon):
            return float(lat), float(lon)
    except Exception:
        pass
    return None, None


def _session_metrics(sess: _Session, ended_at: float) -> Dict[str, Any]:
    pts = decimate_points(sess.points, _min_sample_dist_m())
    length_m = path_length_m(pts)
    swath = _swath_width_m()
    area_m2 = area_from_path_m2(length_m, swath)
    duration_s = max(0.0, ended_at - sess.started_at)
    start = pts[0] if pts else (None, None)
    end = pts[-1] if pts else (None, None)
    return {
        "session_id": sess.session_id,
        "vehicle_id": sess.vehicle_id,
        "source": sess.source,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(sess.started_at)),
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ended_at)),
        "duration_s": round(duration_s, 1),
        "path_length_m": round(length_m, 2),
        "area_m2": round(area_m2, 2),
        "area_ha": round(area_m2 / 10_000.0, 4),
        "swath_width_m": swath,
        "point_count": len(pts),
        "start_lat": start[0],
        "start_lon": start[1],
        "end_lat": end[0],
        "end_lon": end[1],
    }


def _add_to_totals(vehicle_id: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    t = _totals.setdefault(
        vehicle_id,
        {"path_length_m": 0.0, "area_m2": 0.0, "session_count": 0},
    )
    t["path_length_m"] += float(metrics.get("path_length_m") or 0)
    t["area_m2"] += float(metrics.get("area_m2") or 0)
    t["session_count"] += 1
    return {
        "path_length_m": round(t["path_length_m"], 2),
        "area_m2": round(t["area_m2"], 2),
        "area_ha": round(t["area_m2"] / 10_000.0, 4),
        "session_count": int(t["session_count"]),
    }


def on_sprayer_transition(
    vehicle,
    on: bool,
    *,
    source: str = "manual",
    uplink: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Початок/кінець сесії оприскування. Повертає метрики сесії при OFF.
  """
    if not enabled() or vehicle is None:
        return None

    vid = vehicle.id
    lat, lon = _gps_for_vehicle(vehicle)
    now = time.time()

    with _lock:
        if on:
            _active[vid] = _Session(
                vehicle_id=vid,
                session_id=str(uuid.uuid4())[:10],
                started_at=now,
                source=source,
            )
            if lat is not None and lon is not None:
                _active[vid].points.append((lat, lon))
            metrics = None
        else:
            sess = _active.pop(vid, None)
            if sess is None:
                metrics = None
            else:
                if lat is not None and lon is not None:
                    sess.points.append((lat, lon))
                metrics = _session_metrics(sess, now)
                _add_to_totals(vid, metrics)

    if uplink:
        _uplink_transition(vehicle, on, source, metrics)

    return metrics


def _uplink_transition(
    vehicle,
    on: bool,
    source: str,
    metrics: Optional[Dict[str, Any]],
) -> None:
    try:
        from monitoring.event_uplink import push_vehicle_event
    except Exception:
        return

    event_type = "sprayer_on" if on else "sprayer_off"
    detail = "оприскувач увімкнено" if on else "оприскувач вимкнено"
    payload: Dict[str, Any] = {"spray_source": source}
    if metrics:
        payload["spray_coverage"] = metrics
    if not on and metrics:
        detail = (
            f"оприскування: {metrics['path_length_m']:.0f} м, "
            f"{metrics['area_m2']:.0f} м² ({metrics['duration_s']:.0f} с)"
        )
    push_vehicle_event(vehicle, event_type, detail=detail, payload=payload)


def tick_vehicle(vehicle) -> None:
    """Додати GPS-точку, поки sprayer_active."""
    if not enabled() or not getattr(vehicle, "sprayer_active", False):
        return
    vid = vehicle.id
    with _lock:
        sess = _active.get(vid)
    if sess is None:
        on_sprayer_transition(vehicle, True, source="auto", uplink=False)
        with _lock:
            sess = _active.get(vid)
    if sess is None:
        return
    lat, lon = _gps_for_vehicle(vehicle)
    if lat is None or lon is None:
        return
    with _lock:
        sess = _active.get(vid)
        if sess is None:
            return
        if sess.points:
            from monitoring.spray_geo import haversine_m

            last = sess.points[-1]
            if haversine_m(last[0], last[1], lat, lon) < _min_sample_dist_m():
                return
        sess.points.append((lat, lon))


def tick_fleet(fleet) -> None:
    for v in fleet.vehicles.values():
        if getattr(v, "sprayer_active", False):
            tick_vehicle(v)


def vehicle_summary(vehicle_id: str) -> Dict[str, Any]:
    with _lock:
        sess = _active.get(vehicle_id)
        totals = dict(_totals.get(vehicle_id) or {})
    active_metrics = None
    if sess:
        active_metrics = _session_metrics(sess, time.time())
        active_metrics["active"] = True
    return {
        "enabled": enabled(),
        "swath_width_m": _swath_width_m(),
        "active": sess is not None,
        "session": active_metrics,
        "totals": {
            "path_length_m": round(totals.get("path_length_m", 0), 2),
            "area_m2": round(totals.get("area_m2", 0), 2),
            "area_ha": round(totals.get("area_m2", 0) / 10_000.0, 4),
            "session_count": int(totals.get("session_count", 0)),
        },
    }


def reset_totals(vehicle_id: Optional[str] = None) -> None:
    with _lock:
        if vehicle_id:
            _totals.pop(vehicle_id, None)
            _active.pop(vehicle_id, None)
        else:
            _totals.clear()
            _active.clear()


def enrich_vehicle_context(ctx: Dict[str, Any], vehicle_id: str) -> Dict[str, Any]:
    ctx = dict(ctx)
    ctx["spray_coverage"] = vehicle_summary(vehicle_id)
    return ctx
