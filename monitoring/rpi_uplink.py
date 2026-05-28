"""Буфер JPEG з RPi (uplink.source: rpi) — POST /api/monitoring/upload."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from monitoring.cameras import SideCapture, StereoCapture
from monitoring.config_loader import load_monitoring_config


@dataclass
class _VehicleBuffer:
    left: Optional[bytes] = None
    right: Optional[bytes] = None
    left_ts: float = 0.0
    right_ts: float = 0.0


_lock = threading.Lock()
_buffers: Dict[str, _VehicleBuffer] = {}


def uplink_source() -> str:
    cfg = load_monitoring_config().get("uplink") or {}
    return str(cfg.get("source", "local")).lower()


def is_rpi_source() -> bool:
    return uplink_source() == "rpi"


def rpi_wait_timeout_s() -> float:
    cfg = load_monitoring_config().get("uplink") or {}
    rpi = cfg.get("rpi") or {}
    try:
        return max(0.5, float(rpi.get("wait_timeout_s", 10.0)))
    except (TypeError, ValueError):
        return 10.0


def upload_token_expected() -> str:
    cfg = load_monitoring_config().get("uplink") or {}
    rpi = cfg.get("rpi") or {}
    return str(rpi.get("upload_token", "") or "").strip()


def store_upload(
    vehicle_id: str,
    side: str,
    jpeg: bytes,
) -> None:
    """Зберегти кадр від RPi (left / right)."""
    side = side.lower().strip()
    if side not in ("left", "right"):
        raise ValueError("side must be left or right")
    if not jpeg:
        raise ValueError("empty image")
    vid = (vehicle_id or "rover_1").strip()
    now = time.time()
    with _lock:
        buf = _buffers.setdefault(vid, _VehicleBuffer())
        if side == "left":
            buf.left = bytes(jpeg)
            buf.left_ts = now
        else:
            buf.right = bytes(jpeg)
            buf.right_ts = now


def clear_buffer(vehicle_id: Optional[str] = None) -> None:
    with _lock:
        if vehicle_id:
            _buffers.pop(vehicle_id, None)
        else:
            _buffers.clear()


def _decode_jpeg(jpeg: bytes, side: str) -> SideCapture:
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return SideCapture(side=side, error=f"Не вдалося декодувати JPEG ({side})")
        return SideCapture(side=side, frame=frame, jpeg=jpeg)
    except Exception as e:
        return SideCapture(side=side, error=str(e))


def wait_stereo(
    vehicle_id: str,
    timeout_s: Optional[float] = None,
) -> StereoCapture:
    """
    Чекати пару left+right від RPi. Якщо timeout — повертає SideCapture з error.
    """
    timeout = timeout_s if timeout_s is not None else rpi_wait_timeout_s()
    deadline = time.time() + timeout
    vid = (vehicle_id or "rover_1").strip()

    while time.time() < deadline:
        with _lock:
            buf = _buffers.get(vid)
            if buf and buf.left and buf.right:
                left_j, right_j = buf.left, buf.right
                buf.left = None
                buf.right = None
                left = _decode_jpeg(left_j, "left")
                right = _decode_jpeg(right_j, "right")
                return StereoCapture(left=left, right=right)
        time.sleep(0.05)

    return StereoCapture(
        left=SideCapture(
            side="left",
            error=f"RPi: немає left за {timeout:.1f} с (vehicle={vid})",
        ),
        right=SideCapture(
            side="right",
            error=f"RPi: немає right за {timeout:.1f} с (vehicle={vid})",
        ),
    )


def buffer_status(vehicle_id: Optional[str] = None) -> Dict[str, object]:
    with _lock:
        if vehicle_id:
            b = _buffers.get(vehicle_id)
            if not b:
                return {"vehicle_id": vehicle_id, "left": False, "right": False}
            return {
                "vehicle_id": vehicle_id,
                "left": b.left is not None,
                "right": b.right is not None,
                "left_age_s": round(time.time() - b.left_ts, 2) if b.left else None,
                "right_age_s": round(time.time() - b.right_ts, 2) if b.right else None,
            }
        return {
            vid: {
                "left": b.left is not None,
                "right": b.right is not None,
            }
            for vid, b in _buffers.items()
        }
