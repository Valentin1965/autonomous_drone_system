"""Одностороння відправка подій флоту: станція → віддалений сервер (без зображень)."""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional

from monitoring.config_loader import load_monitoring_config
from monitoring.station_config import station_meta
from monitoring.station_context import build_fleet_snapshot, build_vehicle_context


def _remote_cfg() -> dict:
    return load_monitoring_config().get("remote") or {}


def uplink_enabled() -> bool:
    cfg = load_monitoring_config()
    if not cfg.get("enabled", True):
        return False
    rcfg = _remote_cfg()
    if not rcfg.get("sync_events", True):
        return False
    mode = (rcfg.get("mode") or "remote").lower()
    return mode == "remote" and bool(rcfg.get("enabled", True))


def push_event(
    event_type: str,
    *,
    vehicle_id: str = "",
    detail: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    payload: Optional[Dict[str, Any]] = None,
    include_fleet_snapshot: bool = False,
) -> None:
    """Fire-and-forget POST /api/v1/events."""
    if not uplink_enabled():
        return

    meta = station_meta()
    body: Dict[str, Any] = {
        "station_id": meta["station_id"],
        "operator": meta["operator"],
        "vehicle_id": vehicle_id,
        "event_type": event_type,
        "detail": detail,
        "lat": lat,
        "lon": lon,
        "payload": payload or {},
    }
    if include_fleet_snapshot:
        body["payload"]["fleet_snapshot"] = build_fleet_snapshot()

    threading.Thread(
        target=_post_event,
        args=(body,),
        name=f"uplink-{event_type}",
        daemon=True,
    ).start()


def push_vehicle_event(
    vehicle,
    event_type: str,
    *,
    detail: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    ctx = build_vehicle_context(vehicle)
    merged = dict(payload or {})
    merged["vehicle_context"] = ctx
    lat = lon = None
    try:
        from simulator import fleet_registry

        pos = fleet_registry.get_position(vehicle.id)
        if pos:
            lat = float(pos["lat"])
            lon = float(pos["lon"])
    except Exception:
        pass
    push_event(
        event_type,
        vehicle_id=vehicle.id,
        detail=detail,
        lat=lat,
        lon=lon,
        payload=merged,
    )


def _post_event(body: Dict[str, Any]) -> None:
    import requests

    rcfg = _remote_cfg()
    base = (rcfg.get("base_url") or "").rstrip("/")
    url = f"{base}/api/v1/events"
    headers = {"Content-Type": "application/json"}
    key = (rcfg.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    timeout = float(rcfg.get("timeout_s", 45))
    try:
        requests.post(
            url,
            data=json.dumps(body, ensure_ascii=False),
            headers=headers,
            timeout=min(timeout, 15),
        )
    except Exception as e:
        # Зв'язок відсутній → зберегти у чергу офлайн
        try:
            from monitoring.offline_queue import enqueue_event

            enqueue_event(body)
        except Exception as qe:
            print(f"[Monitoring] offline queue error: {qe}")
        print(f"[Monitoring] uplink queued (offline): {e}")
