"""YOLOv8-движок сервера — завантаження моделей та inference."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

_MODELS: Dict[str, Any] = {}
_DEVICE: str = "cpu"
_CONF: float = 0.45


def setup(device: str, confidence: float, weights: Dict[str, str]) -> None:
    """Завантажити моделі. Викликати один раз при старті сервера."""
    global _DEVICE, _CONF, _MODELS
    _DEVICE = device
    _CONF = confidence
    _MODELS = {}
    for crop, path in weights.items():
        if not path:
            continue
        try:
            _MODELS[crop] = _load(path, device)
            print(f"[YOLO] loaded '{crop}' from {path}")
        except Exception as e:
            print(f"[YOLO] failed to load '{crop}' ({path}): {e}")


def _load(path: str, device: str) -> Any:
    from ultralytics import YOLO

    m = YOLO(path)
    try:
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        _ = m(dummy, verbose=False, device=device, conf=0.01)
    except Exception:
        pass
    return m


def model_for(crop: str) -> Optional[Any]:
    return _MODELS.get(crop) or _MODELS.get("default")


def models_loaded() -> List[str]:
    return sorted(_MODELS.keys())


def run(model: Any, img: np.ndarray) -> List[Dict[str, Any]]:
    dets: List[Dict[str, Any]] = []
    results = model(img, verbose=False, device=_DEVICE, conf=_CONF)
    for r in results:
        names = getattr(r, "names", {}) or {}
        boxes = getattr(r, "boxes", None)
        if boxes is None or len(boxes) == 0:
            continue
        for cls_t, conf_t in zip(boxes.cls, boxes.conf):
            try:
                label = str(names[int(cls_t)]).lower()
            except Exception:
                label = "unknown"
            try:
                c = float(conf_t)
            except Exception:
                c = 0.0
            dets.append(
                {
                    "label": label,
                    "confidence": c,
                    "issue_type": _issue_type(label),
                    "severity": _severity(c),
                }
            )
    dets.sort(key=lambda x: x["confidence"], reverse=True)
    return dets


def decode_jpeg(data: bytes) -> Optional[np.ndarray]:
    try:
        import cv2

        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _severity(conf: float) -> str:
    if conf >= 0.75:
        return "high"
    if conf >= 0.5:
        return "medium"
    return "low"


def _issue_type(label: str) -> str:
    lbl = label.lower()
    if any(x in lbl for x in ("mite", "weevil", "aphid", "pest", "worm", "thrips")):
        return "pest"
    if any(x in lbl for x in ("mildew", "rot", "spot", "blight", "sigatoka", "panama")):
        return "disease"
    if "stress" in lbl:
        return "stress"
    return "unknown"
