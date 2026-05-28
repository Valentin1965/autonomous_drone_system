"""API геозони — оператор задає межі на карті."""

from __future__ import annotations

import math

from flask import Blueprint, jsonify, request

from web.fleet import get_fleet, resolve_vehicle_id
from web.geofence import set_bounds, set_disabled
from web.geofence import public_config as geofence_public
from web.session_log import record

geofence_bp = Blueprint("geofence", __name__)


def _request_data():
    return request.get_json(silent=True) or {}


@geofence_bp.route("/api/geofence", methods=["GET"])
def api_geofence_get():
    return jsonify(geofence_public())


@geofence_bp.route("/api/geofence", methods=["PUT"])
def api_geofence_put():
    data = _request_data()
    if not data.get("enabled", True):
        cfg = set_disabled()
        record("geofence_off")
        return jsonify(cfg)

    try:
        lat1 = float(data["min_lat"] if "min_lat" in data else data["lat1"])
        lat2 = float(data["max_lat"] if "max_lat" in data else data["lat2"])
        lon1 = float(data["min_lon"] if "min_lon" in data else data["lon1"])
        lon2 = float(data["max_lon"] if "max_lon" in data else data["lon2"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "bounds_required", "message": "Потрібні min/max lat/lon"}), 400

    try:
        cfg = set_bounds(lat1, lat2, lon1, lon2)
    except ValueError as e:
        return jsonify({"error": "invalid_bounds", "message": str(e)}), 400

    record("geofence_set", f"{cfg['min_lat']:.5f},{cfg['min_lon']:.5f}")
    return jsonify(cfg)


@geofence_bp.route("/api/geofence/from-route", methods=["POST"])
def api_geofence_from_route():
    """Прямокутник за точками маршруту обраного (або вказаного) дрона + відступ."""
    data = _request_data()
    vid = resolve_vehicle_id(request, data)
    v = get_fleet().get_vehicle(vid)
    wps = list(v.mission_waypoints or [])
    if not wps:
        return jsonify({
            "error": "no_waypoints",
            "message": "Спочатку додайте точки маршруту на карті",
        }), 400

    padding_m = float(data.get("padding_m", 25.0))
    cfg = _bounds_from_waypoints(wps, padding_m)
    record("geofence_from_route", f"{v.id}:{len(wps)}")
    return jsonify(cfg)


def _bounds_from_waypoints(waypoints: list, padding_m: float) -> dict:
    lats = [float(w["lat"]) for w in waypoints if w.get("lat") is not None]
    lons = [float(w["lon"]) for w in waypoints if w.get("lon") is not None]
    if not lats or not lons:
        raise ValueError("invalid waypoints")

    mid_lat = sum(lats) / len(lats)
    dlat = padding_m / 111_320.0
    dlon = padding_m / (111_320.0 * max(math.cos(math.radians(mid_lat)), 0.2))

    return set_bounds(
        min(lats) - dlat,
        max(lats) + dlat,
        min(lons) - dlon,
        max(lons) + dlon,
    )
