"""
Детекція перешкод YOLOv8 (COCO): людина, тварини, транспорт тощо.

Використовує стандартну модель detect (yolov8s.pt), не custom seg-класи traversable/obstacle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import cv2
import numpy as np

# COCO — типові об'єкти на шляху rover
DEFAULT_HAZARD_CLASSES = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "suitcase",
    "chair",
    "bench",
)


@dataclass
class HazardHit:
    class_name: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)


@dataclass
class HazardResult:
    stop: bool
    area_ratio: float
    hits: List[HazardHit] = field(default_factory=list)
    label: str = ""

    def summary(self) -> str:
        if not self.hits:
            return ""
        names = sorted({h.class_name for h in self.hits})
        return ", ".join(names[:5])


def _roi_pixels(h: int, w: int, roi_cfg: dict) -> Tuple[int, int, int, int]:
    x_margin = float(roi_cfg.get("x_margin", 0.12))
    y_start = float(roi_cfg.get("y_start", 0.15))
    x0 = int(w * x_margin)
    x1 = int(w * (1.0 - x_margin))
    y0 = int(h * y_start)
    y1 = h
    return x0, y0, x1, y1


def _box_intersection_area(
    bx1: int, by1: int, bx2: int, by2: int, rx0: int, ry0: int, rx1: int, ry1: int
) -> int:
    ix1 = max(bx1, rx0)
    iy1 = max(by1, ry0)
    ix2 = min(bx2, rx1)
    iy2 = min(by2, ry1)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


class HazardDetector:
    """YOLO detect — перешкоди в зоні руху попереду."""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.model_path = str(cfg.get("model") or "yolov8s.pt")
        self.confidence = float(cfg.get("confidence", 0.40))
        self.stop_area_ratio = float(cfg.get("stop_area_ratio", 0.05))
        self.min_box_area_ratio = float(cfg.get("min_box_area_ratio", 0.008))
        raw_classes = cfg.get("classes") or list(DEFAULT_HAZARD_CLASSES)
        self.hazard_classes: Set[str] = {str(c).lower() for c in raw_classes}
        self.roi_cfg = dict(cfg.get("roi") or {})
        self._model = None
        self._device = "cpu"
        self._last: HazardResult = HazardResult(stop=False, area_ratio=0.0)

    def load(self, device: str = "cpu") -> bool:
        if not self.enabled:
            return False
        try:
            from ultralytics import YOLO
        except ImportError as e:
            print(f"[CV] Hazard YOLO: ultralytics недоступний ({e})")
            return False
        try:
            from cv.tracker import resolve_yolo_device

            want = (device or "auto").strip().lower()
            self._device = resolve_yolo_device({"yolo_device": want})
        except Exception:
            self._device = device if device and device != "auto" else "cpu"
        try:
            self._model = YOLO(self.model_path)
            print(
                f"[CV] Hazard YOLO: {self.model_path} "
                f"(device={self._device}, класів={len(self.hazard_classes)})"
            )
            return True
        except Exception as e:
            print(f"[CV] Hazard YOLO не завантажено: {e}")
            self._model = None
            return False

    @property
    def ready(self) -> bool:
        return self._model is not None

    def last_result(self) -> HazardResult:
        return self._last

    def analyze(self, frame: np.ndarray) -> HazardResult:
        if not self.enabled or not self.ready:
            self._last = HazardResult(stop=False, area_ratio=0.0)
            return self._last

        h, w = frame.shape[:2]
        rx0, ry0, rx1, ry1 = _roi_pixels(h, w, self.roi_cfg)
        roi_area = max(1, (rx1 - rx0) * (ry1 - ry0))
        frame_area = max(1, h * w)
        min_box_area = frame_area * self.min_box_area_ratio

        try:
            results = self._model(
                frame, verbose=False, conf=self.confidence, device=self._device
            )
        except RuntimeError as e:
            if self._device != "cpu":
                self._device = "cpu"
                results = self._model(
                    frame, verbose=False, conf=self.confidence, device="cpu"
                )
            else:
                raise e

        hits: List[HazardHit] = []
        covered = 0
        for r in results:
            if r.boxes is None or len(r.boxes) == 0:
                continue
            names = r.names
            for box, cls_t, conf_t in zip(r.boxes.xyxy, r.boxes.cls, r.boxes.conf):
                cls_name = str(names[int(cls_t)]).lower()
                if cls_name not in self.hazard_classes:
                    continue
                x1, y1, x2, y2 = (int(x) for x in box.tolist())
                if (x2 - x1) * (y2 - y1) < min_box_area:
                    continue
                inter = _box_intersection_area(x1, y1, x2, y2, rx0, ry0, rx1, ry1)
                if inter <= 0:
                    continue
                conf = float(conf_t)
                hits.append(
                    HazardHit(
                        class_name=cls_name,
                        confidence=conf,
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                    )
                )
                covered += inter

        area_ratio = min(1.0, covered / roi_area)
        stop = area_ratio >= self.stop_area_ratio
        label = ""
        if stop and hits:
            label = f"СТОП: {hits[0].class_name}"
            if len(hits) > 1:
                label += f" +{len(hits) - 1}"

        self._last = HazardResult(
            stop=stop,
            area_ratio=area_ratio,
            hits=hits,
            label=label,
        )
        return self._last

    def draw(
        self,
        frame: np.ndarray,
        result: Optional[HazardResult] = None,
        *,
        draw_roi: bool = True,
    ) -> np.ndarray:
        out = frame.copy()
        h, w = out.shape[:2]
        rx0, ry0, rx1, ry1 = _roi_pixels(h, w, self.roi_cfg)
        if draw_roi:
            cv2.rectangle(out, (rx0, ry0), (rx1, ry1), (0, 200, 255), 1)
        res = result or self._last
        for hit in res.hits:
            cv2.rectangle(out, (hit.x1, hit.y1), (hit.x2, hit.y2), (0, 80, 255), 2)
            cv2.putText(
                out,
                f"{hit.class_name} {hit.confidence:.2f}",
                (hit.x1, max(0, hit.y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 80, 255),
                2,
            )
        if res.stop:
            cv2.putText(
                out,
                res.label or "STOP — HAZARD",
                (20, 56),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 0, 255),
                3,
            )
        return out
