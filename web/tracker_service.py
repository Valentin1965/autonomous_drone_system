"""Lazy CV tracker with in-process MotionBridge."""

import os

_tracker = None


def get_tracker():
    global _tracker
    if _tracker is None:
        from cv.tracker import YOLOSegmentationTracker, load_cv_config
        from web.motion_bridge import MotionBridge
        from web.state import drone_state

        cfg = load_cv_config()
        source = os.environ.get("CV_SOURCE", "").strip().lower() or None
        _tracker = YOLOSegmentationTracker(
            config=cfg,
            motion=MotionBridge(),
            source=source if source else None,
        )
        _tracker.set_emergency_check(lambda: drone_state.emergency_stop)
    return _tracker


def reset_tracker():
    global _tracker
    if _tracker is not None:
        try:
            _tracker.stop()
        except Exception:
            pass
    _tracker = None


def is_running() -> bool:
    return bool(_tracker and _tracker.running)


def get_jpeg_frame():
    if _tracker is None:
        return None
    return _tracker.get_jpeg_frame()


def get_cv_status() -> dict:
    if _tracker is None:
        return {"running": False, "planner": None, "nav_source": None}
    return _tracker.get_public_status()
