"""Зйомка stereo для моніторингу: локальні камери або RPi uplink."""

from __future__ import annotations

from typing import Optional

from monitoring.cameras import StereoCapture, get_camera_rig
from monitoring.rpi_uplink import is_rpi_source, wait_stereo


def capture_stereo(vehicle_id: Optional[str] = None) -> StereoCapture:
    if is_rpi_source():
        return wait_stereo(vehicle_id or "rover_1")
    return get_camera_rig().capture_stereo()
