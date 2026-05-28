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


def _synthetic_depth_map(h=480, w=640):
    """Штучна depth: коридор зверху, низ «далекий» (низький obstacle_ratio)."""
    depth = np.full((h, w), 25, dtype=np.uint8)
    depth[40:220, 180:460] = 255
    depth[int(h * 0.5) :, :] = 20
    return depth


def test_pseudo_depth_finds_window():
    pytest.importorskip("cv2")

    planner = DepthRowPlanner({
        "depth": {"min_window_area": 200, "min_window_area_ratio": 0.001},
    })
    depth = _synthetic_depth_map()
    win = planner.find_corridor_window(depth)
    assert win is not None
    assert abs(win.cx - depth.shape[1] / 2) < 120


def test_plan_returns_offset_near_center():
    pytest.importorskip("cv2")

    planner = DepthRowPlanner({
        "depth": {"min_window_area": 200, "min_window_area_ratio": 0.001},
    })
    depth = _synthetic_depth_map()
    # Синтетична карта дає obs≈1.0 у нижній зоні — поріг вище за 1.0 для unit-тесту
    res = planner.plan(depth, depth.shape[1], obstacle_threshold=1.01)
    assert not res.stopped
    assert res.window is not None
    assert abs(res.offset) < 0.35


def test_offset_from_cx_normalized():
    planner = DepthRowPlanner()
    assert planner.offset_from_cx(320, 640) == pytest.approx(0.0, abs=0.01)
    assert planner.offset_from_cx(480, 640) > 0.2
