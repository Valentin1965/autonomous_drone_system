"""Контекст станції для відправки на сервер разом із знімками моніторингу."""

from __future__ import annotations

from typing import Any, Dict

from monitoring.station_config import station_meta  # noqa: F401 — re-export


def build_vehicle_context(vehicle) -> Dict[str, Any]:
    """Знімок стану дрона на момент зйомки / події."""
    from web.fleet import get_fleet

    fleet = get_fleet()
    mr = vehicle.mission_runner.status()
    rec = vehicle.mission_record or {}
    ctx = {
        "vehicle_id": vehicle.id,
        "vehicle_name": vehicle.name,
        "control_mode": vehicle.control_mode,
        "sprayer_active": bool(vehicle.sprayer_active),
        "mission": {
            "phase": mr.get("phase"),
            "active": mr.get("active"),
            "index": mr.get("index"),
            "total": mr.get("total"),
            "waypoint_count": len(vehicle.mission_waypoints or []),
        },
        "work_record": {
            "work_started_at": rec.get("work_started_at"),
            "work_finished_at": rec.get("work_finished_at"),
            "spraying": dict(rec.get("spraying") or {}),
            "field_notes": rec.get("field_notes", ""),
        },
        "fleet_emergency_stop": bool(fleet.emergency_stop),
    }
    try:
        from monitoring.spray_coverage import enrich_vehicle_context

        return enrich_vehicle_context(ctx, vehicle.id)
    except Exception:
        return ctx


def build_fleet_snapshot() -> Dict[str, Any]:
    from web.fleet import get_fleet

    fleet = get_fleet()
    return {
        "fleet_count": len(fleet.vehicles),
        "selected_vehicle_id": fleet.selected_id,
        "vehicles": [
            {
                "id": v.id,
                "name": v.name,
                "control_mode": v.control_mode,
                "waypoint_count": len(v.mission_waypoints or []),
                "mission_phase": v.mission_runner.status().get("phase"),
            }
            for v in fleet.vehicles.values()
        ],
    }
