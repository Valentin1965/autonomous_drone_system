"""Depth row planner — без YOLO / камери."""

import numpy as np
import pytest

from cv.depth_row_planner import DepthRowPlanner


def _synthetic_corridor(w=640, h=480):
    """Коридор як у cv/tracker synthetic frame."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :] = (40, 60, 40)
    import cv2

    cx = w // 2

    cv2.rectangle(frame, (cx - 40, 0), (cx + 40, h), (80, 140, 80), -1)
    cv2.rectangle(frame, (0, 0), (w // 2 - 60, h), (50, 100, 50), -1)
    cv2.rectangle(frame, (w // 2 + 60, 0), (w, h), (50, 100, 50), -1)
    return frame


def test_pseudo_depth_finds_window():
    pytest.importorskip("cv2")
    import cv2

    frame = _synthetic_corridor()
    planner = DepthRowPlanner({"depth": {"min_window_area": 800}})
    depth = planner.pseudo_depth_from_rgb(frame)
    win = planner.find_corridor_window(depth)
    assert win is not None
    assert abs(win.cx - frame.shape[1] / 2) < 80


def test_plan_returns_offset_near_center():
    pytest.importorskip("cv2")

    frame = _synthetic_corridor()
    planner = DepthRowPlanner({"depth": {"min_window_area": 800}})
    depth = planner.pseudo_depth_from_rgb(frame)
    res = planner.plan(depth, frame.shape[1], obstacle_threshold=0.95)
    assert not res.stopped
    assert res.window is not None
    assert abs(res.offset) < 0.35


def test_offset_from_cx_normalized():
    planner = DepthRowPlanner()
    assert planner.offset_from_cx(320, 640) == pytest.approx(0.0, abs=0.01)
    assert planner.offset_from_cx(480, 640) > 0.2
