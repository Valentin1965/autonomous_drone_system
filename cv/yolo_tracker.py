"""
DEPRECATED: use cv.tracker.YOLOSegmentationTracker
"""

import warnings

warnings.warn(
    "cv.yolo_tracker is deprecated; use cv.tracker",
    DeprecationWarning,
    stacklevel=2,
)

from cv.tracker import YOLOSegmentationTracker, load_cv_config

__all__ = ["YOLOSegmentationTracker", "load_cv_config"]
