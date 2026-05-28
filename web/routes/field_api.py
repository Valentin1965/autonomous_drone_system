"""API полів — оператор задає полігони на карті."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from web.field import (
    create_field,
    delete_field,
    public_config as field_public,
    select_field,
    set_disabled,
    update_field,
)
from web.session_log import record

field_bp = Blueprint("field", __name__)


def _request_data():
    return request.get_json(silent=True) or {}


@field_bp.route("/api/field", methods=["GET"])
def api_field_get():
    return jsonify(field_public())


@field_bp.route("/api/field", methods=["PUT"])
def api_field_put():
    data = _request_data()
    if not data.get("enabled", True):
        cfg = set_disabled()
        record("field_off")
        return jsonify(cfg)
    poly = data.get("polygon") or data.get("points") or []
    fid = data.get("field_id") or data.get("id")
    name = data.get("name") or ""
    try:
        if fid:
            cfg = update_field(str(fid), name=str(name) if name is not None else None, points=list(poly))
        else:
            cfg = create_field(str(name or "Field"), list(poly))
    except ValueError as e:
        return jsonify({"error": "invalid_polygon", "message": str(e)}), 400
    record("field_set", f"{len((cfg.get('active') or {}).get('polygon') or [])} pts")
    return jsonify(cfg)


@field_bp.route("/api/field/select", methods=["POST"])
def api_field_select():
    data = _request_data()
    fid = data.get("field_id") or data.get("id")
    if not fid:
        return jsonify({"error": "field_id_required"}), 400
    try:
        cfg = select_field(str(fid))
    except ValueError as e:
        return jsonify({"error": "select_failed", "message": str(e)}), 404
    record("field_select", str(fid))
    return jsonify(cfg)


@field_bp.route("/api/field/<field_id>", methods=["DELETE"])
def api_field_delete_one(field_id: str):
    try:
        cfg = delete_field(field_id)
    except ValueError as e:
        return jsonify({"error": "delete_failed", "message": str(e)}), 404
    record("field_delete", field_id)
    return jsonify(cfg)


@field_bp.route("/api/field", methods=["DELETE"])
def api_field_delete():
    cfg = set_disabled()
    record("field_clear")
    return jsonify(cfg)

