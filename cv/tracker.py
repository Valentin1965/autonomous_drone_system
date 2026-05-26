"""
YOLOv8 + depth corridor row navigation — Flask, CLI, hybrid planner.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple

import cv2
import numpy as np
import yaml

from cv.depth_row_planner import DepthPlanResult, DepthRowPlanner


class MotionControl(Protocol):
    def move(self, forward: float, lateral: float, yaw: float = 0.0) -> bool: ...
    def stop(self) -> bool: ...
    def set_sprayer(self, on: bool) -> None: ...


def load_cv_config(path: str = None) -> Dict[str, Any]:
    if path is None:
        try:
            from config.config_paths import cv_config_path

            path = cv_config_path()
        except ImportError:
            path = "config/cv.yaml"
    cfg_path = Path(path)
    if not cfg_path.is_file():
        root = Path(__file__).resolve().parent.parent
        cfg_path = root / path
    if not cfg_path.is_file():
        return {}
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _project_root() -> Path:
    try:
        from config.config_paths import project_root

        return project_root()
    except ImportError:
        return Path(__file__).resolve().parent.parent


def _resolve_media_path(path_str: str, root: Path) -> Optional[Path]:
    """Абсолютний або відносний шлях від кореня проєкту."""
    p = Path(path_str)
    if p.is_file():
        return p.resolve()
    candidate = root / path_str
    if candidate.is_file():
        return candidate.resolve()
    return None


def resolve_video_path(cfg: Dict[str, Any]) -> str:
    """Шлях до відео: video_file або перший файл у video_dir (від кореня проєкту)."""
    root = _project_root()
    vf = (cfg.get("video_file") or "").strip()
    if vf:
        resolved = _resolve_media_path(vf, root)
        if resolved:
            return str(resolved)
    vdir_raw = cfg.get("video_dir", "assets/videos")
    vdir = Path(vdir_raw) if Path(vdir_raw).is_absolute() else root / vdir_raw
    if vdir.is_dir():
        for pattern in ("*.mp4", "*.avi", "*.mov", "*.mkv", "*.MP4", "*.AVI"):
            found = sorted(vdir.glob(pattern))
            if found:
                return str(found[0].resolve())
    demo = vdir / "vineyard_demo.mp4"
    if demo.is_file():
        return str(demo.resolve())
    return ""


def _resolve_source(
    requested: Optional[str],
    cfg: Dict[str, Any],
    video_path: str,
) -> str:
    req = (requested or cfg.get("source") or "video").lower()

    if req in ("webcam", "video", "synthetic"):
        if req == "video" and not video_path:
            if cfg.get("fallback_to_synthetic", False):
                print(
                    "[CV] Немає відео в assets/videos — синтетичний потік "
                    "(покладіть .mp4 або вимкніть fallback_to_synthetic)"
                )
                return "synthetic"
        return req

    if req == "oakd":
        try:
            import depthai  # noqa: F401
            return "oakd"
        except Exception as e:
            if video_path:
                print(f"[CV] Oak-D недоступний ({e}) → video")
                return "video"
            if cfg.get("fallback_to_synthetic", False):
                print(f"[CV] Oak-D недоступний → synthetic")
                return "synthetic"
            raise RuntimeError(
                "Oak-D недоступний і немає відео в assets/videos/. "
                "Додайте .mp4 або встановіть source: video у config/cv.yaml"
            ) from e

    return req


def resolve_yolo_device(cfg: Dict[str, Any]) -> str:
    """
    Ultralytics/PyTorch device. Старі GPU (CC < 7.5, напр. MX130 sm_50) → cpu.
    """
    want = (os.environ.get("YOLO_DEVICE") or cfg.get("yolo_device") or "auto").lower()

    if want == "cpu":
        return "cpu"

    def _cuda_ok() -> bool:
        try:
            import torch
            if not torch.cuda.is_available():
                return False
            major, _minor = torch.cuda.get_device_capability(0)
            return major >= 7
        except Exception:
            return False

    if want.startswith("cuda"):
        if _cuda_ok():
            return want if ":" in want else "cuda:0"
        name = ""
        try:
            import torch
            if torch.cuda.is_available():
                name = torch.cuda.get_device_name(0)
        except Exception:
            pass
        print(f"[CV] GPU {name or 'CUDA'} несумісний з PyTorch → CPU")
        return "cpu"

    # auto
    if _cuda_ok():
        return "cuda:0"
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            cc = torch.cuda.get_device_capability(0)
            print(
                f"[CV] GPU {name} (CC {cc[0]}.{cc[1]}) не підтримується "
                f"цьим PyTorch → CPU"
            )
    except Exception:
        pass
    return "cpu"


def resolve_show_window(cfg: Dict[str, Any]) -> bool:
    """OpenCV imshow потребує DISPLAY (WSL — часто вимкнено)."""
    if os.environ.get("CV_HEADLESS", "").lower() in ("1", "true", "yes"):
        return False
    want = bool(cfg.get("display", {}).get("show_window", False))
    if not want:
        return False
    if not os.environ.get("DISPLAY", "").strip():
        print("[CV] DISPLAY не задано → без вікна (headless). Для GUI: WSLg або export DISPLAY=:0")
        return False
    return True


class YOLOSegmentationTracker:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        motion: Optional[MotionControl] = None,
        source: Optional[str] = None,
    ):
        self.cfg = config or load_cv_config()
        motion_cfg = self.cfg.get("motion", {})
        classes = self.cfg.get("classes", {})

        self.forward_speed = float(motion_cfg.get("forward_speed", 0.70))
        self.lateral_gain = float(motion_cfg.get("lateral_gain", 0.95))
        self.obstacle_stop_threshold = float(motion_cfg.get("obstacle_stop_threshold", 0.24))
        self.depth_obstacle_threshold = float(
            motion_cfg.get("depth_obstacle_stop_ratio", 0.32)
        )
        self.sprayer_tolerance = float(motion_cfg.get("sprayer_row_tolerance", 0.12))
        self.planner_mode = (self.cfg.get("planner") or "hybrid").strip().lower()
        if self.planner_mode not in ("yolo", "depth", "hybrid"):
            self.planner_mode = "hybrid"
        self._depth_planner = DepthRowPlanner(self.cfg)
        self._nav_source = "—"
        self._status_lock = threading.Lock()
        self.cls_traversable = classes.get("traversable", "traversable")
        self.cls_obstacle = classes.get("obstacle", "obstacle")
        self.confidence = float(self.cfg.get("confidence", 0.45))
        self.show_window = resolve_show_window(self.cfg)
        self.window_title = self.cfg.get("display", {}).get("window_title", "Vineyard Row Navigation")

        env_source = os.environ.get("CV_SOURCE", "").strip().lower() or None
        self.fallback_to_synthetic = bool(self.cfg.get("fallback_to_synthetic", False))
        self.video_file = resolve_video_path(self.cfg)
        if self.video_file:
            print(f"[CV] Відеофайл: {self.video_file}")
        self.webcam_index = int(self.cfg.get("webcam_index", 0))

        self.motion = motion
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.model = None
        self._yolo_enabled = self.planner_mode != "depth"
        self.device = None  # DepthAI OAK-D
        self._oakd_rgb_queue = None
        self._oakd_depth_queue = None
        self._yolo_device = "cpu"
        self._cap = None
        self._sprayer_on = False
        self._emergency_check = None
        self._synthetic_t = 0
        self._frame_lock = threading.Lock()
        self._last_jpeg: Optional[bytes] = None
        self._stream_fps = float(self.cfg.get("stream_fps", 8))

        self.source = _resolve_source(
            source or env_source,
            self.cfg,
            self.video_file,
        )

    def set_emergency_check(self, fn) -> None:
        """Callable returning True if motion must stop (e.g. drone_state.emergency_stop)."""
        self._emergency_check = fn

    def _is_emergency(self) -> bool:
        if self._emergency_check:
            return bool(self._emergency_check())
        return False

    def get_best_model_path(self) -> str:
        models_dir = self.cfg.get("model_dir", "models")
        default = self.cfg.get("default_model", "yolov8s-seg.pt")
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)
        pt_files = list(Path(models_dir).glob("*.pt"))
        if pt_files:
            return str(max(pt_files, key=os.path.getmtime))
        return default

    def _load_yolo_model(self) -> bool:
        """Повертає True якщо YOLO завантажено."""
        try:
            from ultralytics import YOLO
        except ImportError as e:
            print(f"[CV] ultralytics не встановлено: {e}")
            return False
        try:
            model_path = self.get_best_model_path()
            self._yolo_device = resolve_yolo_device(self.cfg)
            self.model = YOLO(model_path)
            print(f"[CV] YOLO завантажено: {model_path} (device={self._yolo_device})")
            return True
        except Exception as e:
            print(f"[CV] YOLO не завантажено: {e}")
            return False

    def _prime_first_frame(self) -> None:
        """Один кадр до старту потоку — MJPEG одразу показує відео."""
        frame, depth_raw = self._read_rgb_depth()
        if frame is None:
            return
        h, w = frame.shape[:2]
        use_depth = self.planner_mode in ("depth", "hybrid")
        display = frame
        if use_depth:
            depth_u8 = self._depth_map_for_frame(frame, depth_raw)
            plan = self._depth_planner.plan(
                depth_u8, w, self.depth_obstacle_threshold
            )
            display = self._depth_planner.draw_overlay(frame, depth_u8, plan)
        self._publish_jpeg(display, force=True)

    def start(self):
        if self.running:
            return {"status": "already_running", "source": self.source}

        self.model = None
        self._yolo_enabled = self.planner_mode != "depth"
        yolo_ok = False
        if self._yolo_enabled:
            yolo_ok = self._load_yolo_model()
            if not yolo_ok:
                if self.planner_mode == "hybrid":
                    print("[CV] hybrid → лише depth-коридор (без YOLO)")
                    self._yolo_enabled = False
                else:
                    return {
                        "status": "error",
                        "message": (
                            "YOLO не завантажено. Спробуйте yolo_device: cpu у config/cv.yaml "
                            "або planner: depth"
                        ),
                    }
        else:
            print("[CV] planner=depth — YOLO вимкнено")

        try:
            self._init_capture()
        except RuntimeError as e:
            msg = str(e)
            if self.fallback_to_synthetic and self.source != "synthetic":
                print(f"[CV] {msg} → synthetic")
                self._init_synthetic()
            else:
                print(f"[CV] Помилка захоплення: {msg}")
                return {"status": "error", "message": msg}

        try:
            self._prime_first_frame()
        except Exception as e:
            print(f"[CV] Попередній кадр: {e}")

        self.running = True
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()
        effective = self.planner_mode
        if self.planner_mode == "hybrid" and not self._yolo_enabled:
            effective = "hybrid (depth)"
        print(
            f"[CV] Трекер: planner={effective}, "
            f"джерело={self.source}, motion={type(self.motion).__name__}"
        )
        return {
            "status": "started",
            "source": self.source,
            "planner": self.planner_mode,
            "yolo": yolo_ok,
            "effective_planner": effective,
        }

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
        self._oakd_rgb_queue = None
        self._oakd_depth_queue = None
        if self._cap:
            self._cap.release()
            self._cap = None
        if self.show_window:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
        if self._sprayer_on and self.motion:
            self.motion.set_sprayer(False)
            self._sprayer_on = False
        print("[CV] Трекер зупинено")
        return {"status": "stopped"}

    def _init_oakd(self):
        import depthai as dai

        pipeline = dai.Pipeline()
        cam_rgb = pipeline.create(dai.node.ColorCamera)
        cam_rgb.setPreviewSize(640, 576)
        cam_rgb.setInterleaved(False)
        cam_rgb.setBoardSocket(dai.CameraBoardSocket.CAM_A)

        mono_left = pipeline.create(dai.node.MonoCamera)
        mono_right = pipeline.create(dai.node.MonoCamera)
        stereo = pipeline.create(dai.node.StereoDepth)
        mono_left.setBoardSocket(dai.CameraBoardSocket.CAM_B)
        mono_right.setBoardSocket(dai.CameraBoardSocket.CAM_C)
        stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
        stereo.setLeftRightCheck(True)
        mono_left.out.link(stereo.left)
        mono_right.out.link(stereo.right)

        xout_rgb = pipeline.create(dai.node.XLinkOut)
        xout_rgb.setStreamName("rgb")
        cam_rgb.preview.link(xout_rgb.input)

        xout_depth = pipeline.create(dai.node.XLinkOut)
        xout_depth.setStreamName("depth")
        stereo.depth.link(xout_depth.input)

        self.device = dai.Device(pipeline)
        self._oakd_rgb_queue = self.device.getOutputQueue("rgb", 4, False)
        self._oakd_depth_queue = self.device.getOutputQueue("depth", 4, False)
        print("[CV] Oak-D RGB + depth готово")

    def _init_capture(self):
        if self.source == "oakd":
            self._init_oakd()
            return
        if self.source == "video":
            if not self.video_file:
                vdir = self.cfg.get("video_dir", "assets/videos")
                raise RuntimeError(
                    f"Немає відеофайлу. Покладіть .mp4 у {vdir}/ "
                    f"(див. assets/videos/README.md)"
                )
            self._init_video(self.video_file)
            return
        if self.source == "synthetic":
            self._init_synthetic()
            return
        if self.source == "webcam":
            self._init_webcam()
            return
        raise RuntimeError(f"Невідоме джерело: {self.source}")

    def _init_webcam(self):
        self._cap = cv2.VideoCapture(self.webcam_index)
        if self._cap.isOpened():
            print(f"[CV] Webcam {self.webcam_index} готово")
            return
        self._cap.release()
        self._cap = None
        if self.video_file and Path(self.video_file).is_file():
            print(f"[CV] Webcam недоступна → відеофайл {self.video_file}")
            self._init_video(self.video_file)
            return
        if self.fallback_to_synthetic:
            print(
                "[CV] Webcam недоступна (у WSL часто немає /dev/video0) "
                "→ синтетичний потік для тесту"
            )
            self._init_synthetic()
            return
        raise RuntimeError(
            f"Webcam index={self.webcam_index} недоступна. "
            "WSL: підключіть камеру через usbipd або "
            "встановіть fallback_to_synthetic: true / video_file в config/cv.yaml"
        )

    def _init_video(self, path: str):
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            raise RuntimeError(f"Не вдалося відкрити video_file: {path}")
        self.source = "video"
        print(f"[CV] Відео: {path}")

    def _init_synthetic(self):
        self._cap = None
        self.source = "synthetic"
        self._synthetic_t = 0
        print("[CV] Синтетичний потік 640x480 (тест без камери)")

    def _read_rgb_depth(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Пара (BGR, depth uint8/uint16 або None)."""
        if self.source == "oakd" and self.device and self._oakd_rgb_queue:
            msg = self._oakd_rgb_queue.get()
            frame = msg.getCvFrame()
            depth = None
            if self._oakd_depth_queue:
                dmsg = self._oakd_depth_queue.tryGet()
                if dmsg is not None:
                    depth = dmsg.getFrame()
            return frame, depth

        if self.source == "synthetic":
            frame = self._read_synthetic_frame()
            return frame, None
        if self._cap:
            ok, frame = self._cap.read()
            if ok:
                return frame, None
            if self.source == "video":
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                return (frame, None) if ok else (None, None)
        return None, None

    def _depth_map_for_frame(
        self, frame: np.ndarray, depth_raw: Optional[np.ndarray]
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        if depth_raw is not None:
            return self._depth_planner.normalize_depth(depth_raw, (h, w))
        return self._depth_planner.pseudo_depth_from_rgb(frame)

    def get_public_status(self) -> Dict[str, Any]:
        with self._status_lock:
            nav = self._nav_source
        return {
            "running": self.running,
            "source": self.source,
            "planner": self.planner_mode,
            "nav_source": nav,
        }

    def _set_nav_source(self, src: str) -> None:
        with self._status_lock:
            self._nav_source = src

    def _read_synthetic_frame(self):
        w, h = 640, 480
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:, :] = (40, 60, 40)
        t = self._synthetic_t
        self._synthetic_t += 1
        cx = int(w / 2 + 80 * np.sin(t * 0.05))
        cv2.rectangle(frame, (cx - 40, 0), (cx + 40, h), (80, 140, 80), -1)
        cv2.rectangle(frame, (0, 0), (w // 2 - 60, h), (50, 100, 50), -1)
        cv2.rectangle(frame, (w // 2 + 60, 0), (w, h), (50, 100, 50), -1)
        cv2.putText(
            frame, "SYNTHETIC (no camera)", (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2,
        )
        return frame

    def _run_yolo(self, frame: np.ndarray):
        if self.model is None:
            return []
        try:
            return self.model(
                frame, verbose=False, conf=self.confidence, device=self._yolo_device,
            )
        except RuntimeError as e:
            if self._yolo_device != "cpu":
                print(f"[CV] Помилка CUDA ({e}) → повтор на CPU")
                self._yolo_device = "cpu"
                return self.model(
                    frame, verbose=False, conf=self.confidence, device="cpu",
                )
            raise

    def _parse_yolo_masks(self, results, h: int, w: int):
        left_mask = right_mask = None
        obstacle_area = 0.0
        for r in results:
            if not r.masks:
                continue
            for i, mask_t in enumerate(r.masks.data):
                cls_name = self.model.names[int(r.boxes.cls[i])]
                mask = (mask_t.cpu().numpy() * 255).astype(np.uint8)
                area = np.sum(mask > 0) / (h * w)
                if cls_name == self.cls_traversable:
                    mid = w // 2
                    if np.sum(mask[:, :mid]) > np.sum(mask[:, mid:]):
                        left_mask = mask
                    else:
                        right_mask = mask
                elif cls_name == self.cls_obstacle:
                    obstacle_area += area
        return left_mask, right_mask, obstacle_area

    def _loop_sleep(self) -> None:
        time.sleep(1.0 / max(1.0, self._stream_fps))

    def _tracking_loop(self):
        use_yolo = (
            self.planner_mode in ("yolo", "hybrid")
            and self._yolo_enabled
            and self.model is not None
        )
        use_depth = self.planner_mode in ("depth", "hybrid")

        try:
            self._tracking_loop_body(use_yolo, use_depth)
        except Exception as e:
            print(f"[CV] Fatal error in tracking loop: {e}")
            import traceback

            traceback.print_exc()
            self._do_stop()
        finally:
            self.running = False

    def _tracking_loop_body(self, use_yolo: bool, use_depth: bool):
        while self.running:
            try:
                if self._is_emergency():
                    self._do_stop()
                    self._set_nav_source("stop")
                    continue

                frame, depth_raw = self._read_rgb_depth()
                if frame is None:
                    continue

                h, w = frame.shape[:2]
                left_mask = right_mask = None
                obstacle_area = 0.0
                depth_plan = None
                depth_u8 = None

                if use_depth:
                    depth_u8 = self._depth_map_for_frame(frame, depth_raw)
                    depth_plan = self._depth_planner.plan(
                        depth_u8, w, self.depth_obstacle_threshold
                    )

                if use_yolo:
                    results = self._run_yolo(frame)
                    left_mask, right_mask, obstacle_area = self._parse_yolo_masks(
                        results, h, w
                    )

                yolo_stop = obstacle_area > self.obstacle_stop_threshold
                depth_stop = bool(
                    depth_plan and depth_plan.stopped
                    and depth_plan.obstacle_ratio >= self.depth_obstacle_threshold
                )

                if yolo_stop or depth_stop:
                    self._do_stop()
                    self._set_nav_source("obstacle")
                    display = frame.copy()
                    cv2.putText(
                        display, "STOP - OBSTACLE!", (50, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 255), 4,
                    )
                    if depth_u8 is not None and depth_plan is not None:
                        display = self._depth_planner.draw_overlay(
                            display, depth_u8, depth_plan
                        )
                    self._publish_jpeg(display)
                    if self.show_window:
                        self._show(display)
                    continue

                offset = None
                nav_src = "—"

                if use_depth and depth_plan and depth_plan.window is not None:
                    offset = depth_plan.offset
                    nav_src = "depth"

                if offset is None and use_yolo:
                    offset = self._center_offset(left_mask, right_mask, w)
                    nav_src = "yolo"

                if offset is None:
                    self._do_stop()
                    self._set_nav_source("lost")
                    self._publish_jpeg(frame)
                    continue

                forward = self.forward_speed
                lateral = offset * self.lateral_gain
                self._do_move(forward, lateral)
                self._update_sprayer(offset)
                self._set_nav_source(nav_src)

                if use_depth and depth_u8 is not None and depth_plan is not None:
                    dp = DepthPlanResult(
                        offset=offset,
                        source=nav_src,
                        window=depth_plan.window,
                        obstacle_ratio=depth_plan.obstacle_ratio,
                    )
                    display = self._depth_planner.draw_overlay(frame, depth_u8, dp)
                    if use_yolo and (left_mask is not None or right_mask is not None):
                        display = self._overlay(display, left_mask, right_mask, w)
                else:
                    display = self._overlay(frame, left_mask, right_mask, w)

                self._publish_jpeg(display)
                if self.show_window:
                    self._show(display)
                if self.show_window and cv2.waitKey(1) & 0xFF == 27:
                    break
            finally:
                self._loop_sleep()

    def _overlay(self, frame, left_mask, right_mask, w):
        h = frame.shape[0]
        overlay = frame.copy()
        if left_mask is not None:
            overlay = cv2.addWeighted(
                overlay, 0.7, cv2.cvtColor(left_mask, cv2.COLOR_GRAY2BGR), 0.3, 0,
            )
        if right_mask is not None:
            overlay = cv2.addWeighted(
                overlay, 0.7, cv2.cvtColor(right_mask, cv2.COLOR_GRAY2BGR), 0.3, 0,
            )
        cv2.line(overlay, (w // 2, 0), (w // 2, h), (0, 255, 255), 2)
        return overlay

    def _publish_jpeg(self, frame, force: bool = False) -> None:
        """Останній кадр для MJPEG у веб-панелі."""
        interval = 1.0 / max(1.0, self._stream_fps)
        now = time.time()
        if (
            not force
            and getattr(self, "_last_publish_t", 0)
            and now - self._last_publish_t < interval
        ):
            return
        self._last_publish_t = now
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
        if ok:
            with self._frame_lock:
                self._last_jpeg = buf.tobytes()

    def get_jpeg_frame(self) -> Optional[bytes]:
        with self._frame_lock:
            return self._last_jpeg

    def _show(self, frame):
        if not self.show_window:
            return
        try:
            cv2.imshow(self.window_title, frame)
        except cv2.error as e:
            print(f"[CV] imshow недоступний → headless: {e}")
            self.show_window = False

    def _center_offset(self, left_mask, right_mask, width):
        left_c = right_c = width / 2.0
        if left_mask is not None:
            m = cv2.moments(left_mask)
            if m["m00"] > 5000:
                left_c = m["m10"] / m["m00"]
        if right_mask is not None:
            m = cv2.moments(right_mask)
            if m["m00"] > 5000:
                right_c = m["m10"] / m["m00"]
        center = (left_c + right_c) / 2
        return (center - width / 2) / (width / 2)

    def _do_move(self, forward: float, lateral: float):
        if not self.motion:
            return
        self.motion.move(forward, lateral, 0.0)

    def _do_stop(self):
        if not self.motion:
            return
        self.motion.stop()

    def _update_sprayer(self, offset: float):
        if not self.motion:
            return
        stable = abs(offset) < self.sprayer_tolerance
        if stable and not self._sprayer_on:
            self.motion.set_sprayer(True)
            self._sprayer_on = True
        elif not stable and self._sprayer_on:
            self.motion.set_sprayer(False)
            self._sprayer_on = False


def main():
    import argparse

    p = argparse.ArgumentParser(description="CV row tracker")
    p.add_argument("--webcam", action="store_true", help="Використати webcam замість Oak-D")
    args = p.parse_args()
    from web.motion_bridge import PrintMotion

    source = "webcam" if args.webcam else None
    tracker = YOLOSegmentationTracker(motion=PrintMotion(), source=source)
    tracker.start()
    try:
        while tracker.running:
            time.sleep(1)
    except KeyboardInterrupt:
        tracker.stop()


if __name__ == "__main__":
    main()
