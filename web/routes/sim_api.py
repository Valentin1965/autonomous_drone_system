"""API для розробки на симуляторі (лише коли sim зареєстровано)."""

from flask import Blueprint, jsonify, request

from web.session_log import record
from web.fleet import get_fleet

sim_bp = Blueprint("sim", __name__)


def _sim_required():
    from simulator.registry import get_sim

    sim = get_sim()
    if sim is None:
        return None, (jsonify({
            "error": "no_simulator",
            "message": "Симулятор не запущено. Запустіть: python main.py --full",
        }), 503)
    return sim, None


@sim_bp.route("/api/sim/status", methods=["GET"])
def sim_status():
    sim, err = _sim_required()
    if err:
        return err
    pos = sim.get_position()
    return jsonify({
        "simulator": True,
        "position": pos,
        "waypoints": len(get_fleet().selected.mission_waypoints),
    })


@sim_bp.route("/api/sim/load_demo", methods=["POST"])
def sim_load_demo():
    sim, err = _sim_required()
    if err:
        return err
    from utils.demo_mission import apply_demo_to_state
    from simulator.registry import snap_to

    try:
        out = apply_demo_to_state()
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404

    if out.get("waypoints"):
        w0 = out["waypoints"][0]
        snap_to(w0["lat"], w0["lon"])
    record("sim_load_demo", f"{out.get('count', 0)} wp")
    return jsonify({"status": "ok", **out})


@sim_bp.route("/api/sim/reset", methods=["POST"])
def sim_reset():
    """Скинути на точку 1 маршруту або на дефолтний центр."""
    sim, err = _sim_required()
    if err:
        return err
    from simulator.registry import snap_to, halt_motion

    halt_motion()
    wps = get_fleet().selected.mission_waypoints
    if wps:
        snap_to(wps[0]["lat"], wps[0]["lon"])
        lat, lon = wps[0]["lat"], wps[0]["lon"]
    else:
        from simulator.registry import DEFAULT_SIM_LAT, DEFAULT_SIM_LON

        snap_to(DEFAULT_SIM_LAT, DEFAULT_SIM_LON)
        lat, lon = DEFAULT_SIM_LAT, DEFAULT_SIM_LON
    record("sim_reset")
    return jsonify({"status": "ok", "lat": lat, "lon": lon})


@sim_bp.route("/api/sim/battery", methods=["POST"])
def sim_battery():
    sim, err = _sim_required()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    pct = data.get("percent", data.get("battery_pct", 95))
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return jsonify({"error": "percent required"}), 400
    pct = max(0.0, min(100.0, pct))
    with sim.lock:
        sim.battery_remaining = pct
    return jsonify({"battery_pct": pct})
