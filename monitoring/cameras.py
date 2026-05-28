"""Дві камери моніторингу (ліва / права) — незалежні від CV ряду."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from monitoring.config_loader import load_monitoring_config


@dataclass
class SideCapture:
    side: str
    frame: Optional[np.ndarray] = None
    error: str = ""
    jpeg: Optional[bytes] = None


@dataclass
class StereoCapture:
    left: SideCapture
    right: SideCapture

    def both_ok(self) -> bool:
        return self.left.frame is not None and self.right.frame is not None

    def any_ok(self) -> bool:
        return self.left.frame is not None or self.right.frame is not None


class MonitoringCamera:
    """Одна бокова камера (будь-який тип джерела)."""

    def __init__(self, side: str, cfg: Dict[str, Any]):
        self.side = side
        self.cfg = cfg
        self.type = (cfg.get("type") or "synthetic").lower()
        self.source = str(cfg.get("source", "0"))
        self.label = str(cfg.get("label") or side)
        self._cap = None

    def status(self) -> Dict[str, Any]:
        return {
            "side": self.side,
            "type": self.type,
            "source": self.source,
            "label": self.label,
            "open": self._cap is not None and self._cap.isOpened()
            if self.type in ("webcam", "rtsp")
            else self.type == "file" and Path(self.source).is_file(),
        }

    def _open(self) -> bool:
        if self.type == "webcam":
            idx = int(self.source)
            self._cap = cv2.VideoCapture(idx)
            return self._cap.isOpened()
        if self.type == "rtsp":
            self._cap = cv2.VideoCapture(self.source)
            return self._cap.isOpened()
        return True

    def capture(self) -> SideCapture:
        if self.type == "file":
            return self._capture_file()
        if self.type == "synthetic":
            return self._capture_synthetic()
        if self._cap is None or not self._cap.isOpened():
            if not self._open():
                return SideCapture(
                    side=self.side,
                    error=f"Камера {self.side} недоступна ({self.type})",
                )
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return SideCapture(side=self.side, error=f"Порожній кадр {self.side}")
        jpeg = self._encode_jpeg(frame)
        return SideCapture(side=self.side, frame=frame, jpeg=jpeg)

    def _capture_file(self) -> SideCapture:
        try:
            from monitoring.config_loader import _root

            p = Path(self.source)
            if not p.is_file():
                p = _root() / self.source
            if not p.is_file():
                return SideCapture(side=self.side, error=f"Файл не знайдено: {self.source}")
            frame = cv2.imread(str(p))
            if frame is None:
                return SideCapture(side=self.side, error=f"Не вдалося прочитати {p}")
            jpeg = self._encode_jpeg(frame)
            return SideCapture(side=self.side, frame=frame, jpeg=jpeg)
        except Exception as e:
            return SideCapture(side=self.side, error=str(e))

    def _capture_synthetic(self) -> SideCapture:
        w, h = 640, 480
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        base = (35, 80, 35) if self.side == "left" else (40, 70, 45)
        frame[:, :] = base
        if self.side == "left":
            cv2.rectangle(frame, (180, 120), (420, 400), (50, 120, 50), -1)
            cv2.rectangle(frame, (260, 220), (310, 280), (45, 55, 130), -1)
        else:
            cv2.rectangle(frame, (220, 100), (460, 380), (55, 110, 45), -1)
        cv2.putText(
            frame,
            f"MON {self.side.upper()}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (220, 220, 220),
            2,
        )
        jpeg = self._encode_jpeg(frame)
        return SideCapture(side=self.side, frame=frame, jpeg=jpeg)

    @staticmethod
    def _encode_jpeg(frame: np.ndarray) -> Optional[bytes]:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if ok else None

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


class DualCameraRig:
    def __init__(self):
        cfg = load_monitoring_config()
        cams = cfg.get("cameras") or {}
        self.left = MonitoringCamera("left", cams.get("left") or {"type": "synthetic"})
        self.right = MonitoringCamera("right", cams.get("right") or {"type": "synthetic"})

    def status(self) -> Dict[str, Any]:
        return {
            "left": self.left.status(),
            "right": self.right.status(),
        }

    def capture_stereo(self) -> StereoCapture:
        return StereoCapture(left=self.left.capture(), right=self.right.capture())

    def release(self) -> None:
        self.left.release()
        self.right.release()


_rig: Optional[DualCameraRig] = None


def get_camera_rig(reload: bool = False) -> DualCameraRig:
    global _rig
    if _rig is None or reload:
        if _rig is not None:
            _rig.release()
        _rig = DualCameraRig()
    return _rig
