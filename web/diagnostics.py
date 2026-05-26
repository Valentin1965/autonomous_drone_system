"""Build health / session-log payloads."""

from __future__ import annotations

import os
import time
from typing import Any, Dict

from web.app_meta import APP_VERSION, uptime_s
from web.session_log import recent


def _deployment_info(cfg: dict) -> Dict[str, Any]:
    return {
        "deployment": cfg.get("deployment"),
        "role": cfg.get("role"),
        "system_config": os.environ.get("SYSTEM_CONFIG", "config/system.yaml"),
        "cv_config": os.environ.get("CV_CONFIG", "config/cv.yaml"),
    }


def build_health() -> Dict[str, Any]:
    from config.config_paths import cv_config_path, system_config_path
    from mavlink.runtime_config import client_connection_string, mavlink_profile
    from simulator.registry import get_sim
    from web.mission_runner import mission_runner
    from web.state import drone_state
    from web.tracker_service import get_cv_status, is_running

    cfg = drone_state.load_config()
    profile = mavlink_profile(cfg)
    sim = get_sim() is not None
    warnings = []
    if profile == "px4" and sim:
        warnings.append(
            "Профіль px4, але активний симулятор (--full). "
            "Для поля: MAVLINK_PROFILE=px4 без симулятора."
        )
    if profile == "sim" and not sim:
        warnings.append(
            "Профіль sim, симулятор не запущено. "
            "Запустіть: python main.py --full або --simulator."
        )

    try:
        ctrl = drone_state.get_controller()
        st = ctrl.get_status()
    except Exception as e:
        st = {"connected": False, "error": str(e)}

    return {
        "ok": True,
        "version": APP_VERSION,
        "uptime_s": round(uptime_s(), 1),
        "ts": time.time(),
        "vehicle_type": "ground_rover",
        "mavlink_profile": profile,
        "mavlink_connection": client_connection_string(cfg, profile),
        "simulator_active": sim,
        "warnings": warnings,
        "mavlink": st,
        "control_mode": drone_state.get_control_mode(),
        "mission": mission_runner.status(),
        "cv": {**get_cv_status(), "running": is_running()},
        "paths": {
            "system": str(system_config_path()),
            "cv": cv_config_path(),
        },
        **_deployment_info(cfg),
    }


def build_session_log_text() -> str:
    from web.mission_runner import mission_runner
    from web.state import drone_state

    health = build_health()
    lines = [
        f"# GCS session log — {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"version={health.get('version')} uptime_s={health.get('uptime_s')}",
        f"mavlink_profile={health.get('mavlink_profile')} "
        f"connection={health.get('mavlink_connection')}",
        f"simulator_active={health.get('simulator_active')}",
        f"control_mode={health.get('control_mode')}",
        "",
        "## Warnings",
    ]
    for w in health.get("warnings") or []:
        lines.append(f"- {w}")
    if not health.get("warnings"):
        lines.append("- (none)")

    lines.extend(["", "## Mission", str(health.get("mission"))])
    lines.extend(["", "## Waypoints", str(drone_state.mission_waypoints)])
    lines.extend(["", "## Events"])
    for ev in recent(300):
        t = time.strftime("%H:%M:%S", time.localtime(ev["ts"]))
        detail = f" — {ev['detail']}" if ev.get("detail") else ""
        lines.append(f"[{t}] {ev.get('level', 'info')}: {ev.get('event')}{detail}")
    return "\n".join(lines) + "\n"
