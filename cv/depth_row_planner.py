"""
Локальний planner ряду за картою глибини (ідеї PIC4SeR / vineyard depth corridor).

Працює з реальною depth (Oak-D) або псевдо-depth з RGB (відео / synthetic для dev).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np


@dataclass
class CorridorWindow:
    """«Вікно» коридору в кінці ряду (центр для P-регулятора)."""

    cx: float
    cy: float
    x: int
    y: int
    w: int
    h: int
    area: float


@dataclass
class DepthPlanResult:
    offset: float
    source: str
    window: Optional[CorridorWindow] = None
    obstacle_ratio: float = 0.0
    stopped: bool = False


def load_depth_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(cfg.get("depth") or {})
    return {
        "near_far_ratio": float(d.get("near_far_ratio", 0.55)),
        "min_window_area": float(d.get("min_window_area", 2500)),
        "min_window_area_ratio": float(d.get("min_window_area_ratio", 0.02)),
        "center_band_ratio": float(d.get("center_band_ratio", 0.35)),
        "obstacle_close_ratio": float(d.get("obstacle_close_ratio", 0.28)),
        "morph_kernel": int(d.get("morph_kernel", 5)),
        "canny_low": int(d.get("canny_low", 40)),
        "canny_high": int(d.get("canny_high", 120)),
    }


class DepthRowPlanner:
    """Depth / pseudo-depth → центр коридору → нормалізований offset [-1, 1]."""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = load_depth_config(cfg or {})

    def pseudo_depth_from_rgb(self, bgr: np.ndarray) -> np.ndarray:
        """
        Наближена карта глибини з RGB (для відео без depth-камери).
        Нижня частина кадру + темніші ділянки → «ближче».
        """
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        y_w = np.linspace(0.35, 1.0, h, dtype=np.float32).reshape(-1, 1)
        inv = (255.0 - gray.astype(np.float32)) / 255.0
        depth_f = inv * y_w
        depth_u8 = np.clip(depth_f * 255.0, 0, 255).astype(np.uint8)
        depth_u8 = cv2.GaussianBlur(depth_u8, (5, 5), 0)
        return depth_u8

    def normalize_depth(self, depth: np.ndarray, target_hw: Tuple[int, int]) -> np.ndarray:
        """Привести depth до uint8 HxW (мм, disparity або псевдо)."""
        th, tw = target_hw
        if depth is None:
            raise ValueError("depth is None")
        d = depth
        if d.ndim == 3:
            d = d[:, :, 0]
        if d.shape[0] != th or d.shape[1] != tw:
            d = cv2.resize(d, (tw, th), interpolation=cv2.INTER_LINEAR)
        if d.dtype == np.uint16:
            d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        elif d.dtype != np.uint8:
            d = cv2.normalize(d.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(
                np.uint8
            )
        return d

    def find_corridor_window(self, depth: np.ndarray) -> Optional[CorridorWindow]:
        """
        Знайти найбільший «далекий» коридор у верхній/середній зоні (vineyard window).
        """
        h, w = depth.shape[:2]
        min_area = max(
            self.cfg["min_window_area"],
            h * w * self.cfg["min_window_area_ratio"],
        )

        center = depth[:, int(w * 0.25) : int(w * 0.75)]
        if center.size == 0:
            return None
        thresh_val = float(np.percentile(center, self.cfg["near_far_ratio"] * 100))
        _, far = cv2.threshold(depth, thresh_val, 255, cv2.THRESH_BINARY)

        k = max(3, self.cfg["morph_kernel"] | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
        far = cv2.morphologyEx(far, cv2.MORPH_CLOSE, kernel)
        far = cv2.morphologyEx(far, cv2.MORPH_OPEN, kernel)

        upper = far[: int(h * 0.72), :]
        edges = cv2.Canny(upper, self.cfg["canny_low"], self.cfg["canny_high"])
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best: Optional[CorridorWindow] = None
        best_area = 0.0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            aspect = bw / max(bh, 1)
            if aspect < 0.35 or aspect > 6.0:
                continue
            M = cv2.moments(cnt)
            if M["m00"] < 1:
                continue
            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]
            if best is None or area > best_area:
                best_area = area
                best = CorridorWindow(
                    cx=float(cx),
                    cy=float(y),
                    x=int(x),
                    y=int(y),
                    w=int(bw),
                    h=int(bh),
                    area=float(area),
                )
        return best

    def offset_from_cx(self, cx: float, width: int) -> float:
        return float((cx - width / 2.0) / max(width / 2.0, 1.0))

    def center_obstacle_ratio(self, depth: np.ndarray) -> float:
        """Частка «близьких» пікселів у центральній нижній зоні."""
        h, w = depth.shape[:2]
        band = self.cfg["center_band_ratio"]
        x0 = int(w * (0.5 - band / 2))
        x1 = int(w * (0.5 + band / 2))
        roi = depth[int(h * 0.45) :, x0:x1]
        if roi.size == 0:
            return 0.0
        close_thr = float(np.percentile(roi, 72))
        return float(np.mean(roi >= close_thr))

    def plan(
        self,
        depth: np.ndarray,
        width: int,
        obstacle_threshold: float,
    ) -> DepthPlanResult:
        obs = self.center_obstacle_ratio(depth)
        if obs >= obstacle_threshold:
            return DepthPlanResult(
                offset=0.0,
                source="depth",
                obstacle_ratio=obs,
                stopped=True,
            )

        window = self.find_corridor_window(depth)
        if window is None:
            return DepthPlanResult(
                offset=0.0,
                source="depth",
                obstacle_ratio=obs,
                stopped=False,
            )

        off = self.offset_from_cx(window.cx, width)
        return DepthPlanResult(
            offset=off,
            source="depth",
            window=window,
            obstacle_ratio=obs,
            stopped=False,
        )

    def draw_overlay(
        self,
        frame: np.ndarray,
        depth: np.ndarray,
        result: DepthPlanResult,
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        out = frame.copy()
        cv2.line(out, (w // 2, 0), (w // 2, h), (0, 255, 255), 2)

        if result.window is not None:
            win = result.window
            cv2.rectangle(
                out,
                (win.x, win.y),
                (win.x + win.w, win.y + win.h),
                (255, 180, 0),
                2,
            )
            cv2.circle(out, (int(win.cx), int(win.cy)), 6, (0, 200, 255), -1)

        depth_vis = cv2.applyColorMap(depth, cv2.COLORMAP_MAGMA)
        depth_vis = cv2.resize(depth_vis, (w // 4, h // 4))
        out[0 : depth_vis.shape[0], 0 : depth_vis.shape[1]] = depth_vis

        label = f"ROW {result.source.upper()}"
        if result.stopped:
            label += " STOP"
        cv2.putText(
            out,
            label,
            (12, h - 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (200, 255, 200),
            2,
        )
        return out
