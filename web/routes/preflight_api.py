"""Preflight API — перевірка готовності для обраного дрона (флот / sim)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from web.fleet import get_fleet, resolve_vehicle_id
from web.preflight import evaluate

preflight_bp = Blueprint("preflight", __name__)


def _vehicle_status(vehicle) -> dict:
    status = vehicle.get_controller().get_status()
    gps = dict(status.get("gps") or {})
    try:
        from simulator import fleet_registry

        sim_gps = fleet_registry.get_position(vehicle.id)
        if sim_gps:
            gps = dict(sim_gps)
            status["gps_source"] = "simulator"
    except Exception:
        pass
    status["gps"] = gps
    return status


@preflight_bp.route("/api/preflight", methods=["GET"])
def api_preflight():
    """
  GET /api/preflight?vehicle_id=rover_2&require_route=1
  Повертає той самий блок, що в /api/status → preflight.
    """
    vid = resolve_vehicle_id(request, {})
    v = get_fleet().get_vehicle(vid)
    status = _vehicle_status(v)
    require_route = request.args.get("require_route", "").lower() in ("1", "true", "yes")
    pf = evaluate(
        v,
        mavlink_status=status,
        require_route=require_route,
        require_arm=True,
    )
    return jsonify({"vehicle_id": v.id, "vehicle_name": v.name, **pf})
