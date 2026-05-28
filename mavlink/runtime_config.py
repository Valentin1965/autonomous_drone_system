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


def _link_role(system_cfg: Dict[str, Any]) -> str:
    """gcs_radio | rpi_usb | sim | '' (auto)."""
    mavlink = system_cfg.get("mavlink", {})
    link = str(mavlink.get("link") or "").strip().lower()
    if link:
        return link
    role = str(system_cfg.get("role") or "").strip().lower()
    if role == "ground_station":
        return "gcs_radio"
    if role == "rpi_companion":
        return "rpi_usb"
    return ""


def client_connection_string(system_cfg: Dict[str, Any], profile: str = None) -> str:
    """Endpoint for GroundController (client → vehicle)."""
    mavlink = system_cfg.get("mavlink", {})
    profile = profile or mavlink_profile(system_cfg)
    link = _link_role(system_cfg)

    if profile == "px4":
        if link == "gcs_radio":
            return (
                mavlink.get("connection_gcs")
                or mavlink.get("connection_px4")
                or mavlink.get("connection_string")
                or "udp:127.0.0.1:14550"
            )
        if link == "rpi_usb":
            return (
                mavlink.get("connection_rpi")
                or mavlink.get("connection_px4")
                or mavlink.get("connection_string")
                or "serial:/dev/ttyACM0:115200"
            )
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


def mavlink_link_description(system_cfg: Dict[str, Any]) -> str:
    """Людський опис активного каналу (для логів / UI)."""
    profile = mavlink_profile(system_cfg)
    link = _link_role(system_cfg)
    conn = client_connection_string(system_cfg, profile)
    if profile == "sim":
        return f"sim · {conn}"
    if link == "gcs_radio":
        return f"GCS radio · {conn}"
    if link == "rpi_usb":
        return f"RPi USB · {conn}"
    return f"px4 · {conn}"
