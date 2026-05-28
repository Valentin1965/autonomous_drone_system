"""Аналіз кадру: YOLO (якщо є модель) або демо/заглушка."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class Detection:
    issue_type: str
    label: str
    confidence: float
    severity: str = "medium"
    camera_side: str = ""


@dataclass
class AnalyzeResult:
    detections: List[Detection] = field(default_factory=list)
    model_status: str = "not_loaded"
    message: str = ""


class PlantHealthDetector:
    def __init__(self, crop_id: str, crop_cfg: Dict[str, Any]):
        self.crop_id = crop_id
        self.crop_cfg = crop_cfg
        self._model = None
        self._device = "cpu"
        self._model_path = (crop_cfg.get("model") or "").strip()
        self._threshold = float(crop_cfg.get("confidence_threshold", 0.45))
        self._labels = [str(x) for x in (crop_cfg.get("issue_labels") or [])]

    def load(self) -> bool:
        if not self._model_path:
            return False
        try:
            from ultralytics import YOLO
            from cv.tracker import resolve_yolo_device

            from monitoring.config_loader import load_monitoring_config

            cfg = load_monitoring_config()
            self._device = resolve_yolo_device(
                {"yolo_device": cfg.get("yolo_device", "auto")}
            )
            self._model = YOLO(self._model_path)
            print(f"[Monitoring] Модель {self.crop_id}: {self._model_path}")
            return True
        except Exception as e:
            print(f"[Monitoring] Модель не завантажена ({self.crop_id}): {e}")
            self._model = None
            return False

    @property
    def ready(self) -> bool:
        return self._model is not None

    def analyze(
        self,
        frame: np.ndarray,
        *,
        demo_mode: bool = False,
    ) -> AnalyzeResult:
        if frame is None or frame.size == 0:
            return AnalyzeResult(
                detections=[],
                model_status="no_frame",
                message="Немає кадру",
            )

        if self.ready:
            return self._analyze_yolo(frame)

        if demo_mode and self._labels:
            return self._demo_detection(frame)

        return AnalyzeResult(
            detections=[],
            model_status="pending_model",
            message=(
                "Модель для культури не підключена. "
                "Додайте .pt у config/monitoring.yaml або увімкніть demo_findings_in_sim."
            ),
        )

    def _analyze_yolo(self, frame: np.ndarray) -> AnalyzeResult:
        detections: List[Detection] = []
        try:
            results = self._model(
                frame, verbose=False, conf=self._threshold, device=self._device
            )
        except RuntimeError:
            results = self._model(
                frame, verbose=False, conf=self._threshold, device="cpu"
            )

        allowed = {lbl.lower() for lbl in self._labels}
        for r in results:
            names = r.names
            boxes = getattr(r, "boxes", None)
            if boxes is None or len(boxes) == 0:
                continue
            for box, cls_t, conf_t in zip(boxes.xyxy, boxes.cls, boxes.conf):
                label = str(names[int(cls_t)]).lower()
                if allowed and label not in allowed:
                    continue
                conf = float(conf_t)
                detections.append(
                    Detection(
                        issue_type=self._issue_type_for(label),
                        label=label,
                        confidence=conf,
                        severity=self._severity(conf),
                    )
                )

        return AnalyzeResult(
            detections=detections,
            model_status="yolo",
            message=f"Знайдено: {len(detections)}",
        )

    def _demo_detection(self, frame: np.ndarray) -> AnalyzeResult:
        """Один приклад знахідки для перевірки карти (симуляція)."""
        h, w = frame.shape[:2]
        green = frame[:, :, 1].astype(np.float32)
        stress = float(np.mean(green < 80))
        if stress < 0.08:
            return AnalyzeResult(
                detections=[],
                model_status="demo",
                message="Демо: ознак стресу не виявлено",
            )
        label = self._labels[0] if self._labels else "suspect"
        return AnalyzeResult(
            detections=[
                Detection(
                    issue_type=self._issue_type_for(label),
                    label=f"{label}_suspect",
                    confidence=0.55,
                    severity="low",
                )
            ],
            model_status="demo",
            message="Демо-режим (підключіть навчену модель для поля)",
        )

    @staticmethod
    def _issue_type_for(label: str) -> str:
        lbl = label.lower()
        if any(x in lbl for x in ("mite", "weevil", "aphid", "pest", "worm")):
            return "pest"
        if any(x in lbl for x in ("mildew", "rot", "spot", "blight", "sigatoka")):
            return "disease"
        if "stress" in lbl:
            return "stress"
        return "unknown"

    @staticmethod
    def _severity(confidence: float) -> str:
        if confidence >= 0.75:
            return "high"
        if confidence >= 0.5:
            return "medium"
        return "low"
