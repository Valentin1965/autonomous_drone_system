"""Resolve MAVLink connection strings from config and environment."""

import os
from typing import Any, Dict


def mavlink_profile(system_cfg: Dict[str, Any]) -> str:
    """Active profile: 'sim' (default) or 'px4'."""
    env = os.environ.get("MAVLINK_PROFILE", "").strip().lower()
    if env in ("sim", "px4"):
        return env
    mavlink = system_cfg.get("mavlink", {})
    return (mavlink.get("active") or "sim").lower()


def client_connection_string(system_cfg: Dict[str, Any], profile: str = None) -> str:
    """UDP endpoint for GroundController / Flask (client → vehicle)."""
    mavlink = system_cfg.get("mavlink", {})
    profile = profile or mavlink_profile(system_cfg)
    if profile == "px4":
        return (
            mavlink.get("connection_px4")
            or mavlink.get("connection_string")
            or "udp:127.0.0.1:14550"
        )
    return (
        mavlink.get("connection_sim")
        or mavlink.get("connection_string")
        or "udp:127.0.0.1:14550"
    )


def simulator_bind_string(system_cfg: Dict[str, Any]) -> str:
    """UDP listen endpoint for PixhawkGPSSimulator."""
    sim = system_cfg.get("simulator", {})
    return sim.get("connection_string", "udpin:0.0.0.0:14550")
