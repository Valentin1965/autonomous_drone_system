# cv/yolov8_tracker.py
import cv2
import numpy as np
import threading
import time
import requests
import os
from pathlib import Path
from ultralytics import YOLO
import depthai as dai

class YOLOSegmentationTracker:
    def __init__(self):
        self.running = False
        self.thread = None
        self.model = None
        self.device = None

        self.forward_speed = 0.70
        self.lateral_gain = 0.95
        self.center_tolerance = 0.10
        self.obstacle_stop_threshold = 0.24

    def get_best_model_path(self):
        models_dir = "models"
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)
        pt_files = list(Path(models_dir).glob("*.pt"))
        return str(max(pt_files, key=os.path.getmtime)) if pt_files else "yolov8s-seg.pt"

    def start(self):
        if self.running:
            print("[CV] Трекер вже запущений")
            return False

        # Завантаження моделі
        model_path = self.get_best_model_path()
        self.model = YOLO(model_path)
        print(f"[CV] YOLOv8-seg модель завантажена: {model_path}")

        # Ініціалізація Oak-D
        self.init_oakd()

        self.running = True
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()
        print("[CV] YOLO Трекер запущено")
        return True

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        if self.device:
            self.device.close()
        print("[CV] Трекер зупинено")

    def init_oakd(self):
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
        xout_depth = pipeline.create(dai.node.XLinkOut)
        xout_rgb.setStreamName("rgb")
        xout_depth.setStreamName("depth")

        cam_rgb.preview.link(xout_rgb.input)
        stereo.depth.link(xout_depth.input)

        self.device = dai.Device(pipeline)
        print("[CV] Oak-D камера ініціалізована")

    def _tracking_loop(self):
        rgb_q = self.device.getOutputQueue("rgb", 4, False)
        depth_q = self.device.getOutputQueue("depth", 4, False)

        while self.running:
            rgb_msg = rgb_q.get()
            depth_msg = depth_q.get()

            frame = rgb_msg.getCvFrame()
            depth_frame = depth_msg.getFrame()

            h, w = frame.shape[:2]
            results = self.model(frame, verbose=False, conf=0.45)

            left_mask = right_mask = None
            obstacle_area = 0.0

            for r in results:
                if not r.masks: continue
                for i, mask_t in enumerate(r.masks.data):
                    cls_name = self.model.names[int(r.boxes.cls[i])]
                    mask = (mask_t.cpu().numpy() * 255).astype(np.uint8)
                    area = np.sum(mask > 0) / (h * w)

                    if cls_name == "traversable":
                        mid = w // 2
                        if np.sum(mask[:, :mid]) > np.sum(mask[:, mid:]):
                            left_mask = mask
                        else:
                            right_mask = mask
                    elif cls_name == "obstacle":
                        obstacle_area += area

            if obstacle_area > self.obstacle_stop_threshold:
                self._send_stop()
                cv2.putText(frame, "STOP - OBSTACLE!", (50, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0,0,255), 4)
                continue

            offset = self.calculate_center_offset(left_mask, right_mask, w)
            forward = self.forward_speed
            lateral = offset * self.lateral_gain

            self._send_move(forward, lateral)

            # Візуалізація
            overlay = frame.copy()
            if left_mask is not None:
                overlay = cv2.addWeighted(overlay, 0.7, cv2.cvtColor(left_mask, cv2.COLOR_GRAY2BGR), 0.3, 0)
            if right_mask is not None:
                overlay = cv2.addWeighted(overlay, 0.7, cv2.cvtColor(right_mask, cv2.COLOR_GRAY2BGR), 0.3, 0)

            cv2.line(overlay, (w//2, 0), (w//2, h), (0, 255, 255), 2)
            cv2.imshow("Vineyard Row Navigation", overlay)

            if cv2.waitKey(1) & 0xFF == 27:
                break

    def calculate_center_offset(self, left_mask, right_mask, width):
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

    def _send_move(self, forward, lateral):
        try:
            requests.post("http://127.0.0.1:8080/api/move",
                          json={"forward": forward, "lateral": lateral, "yaw": 0}, timeout=0.15)
        except:
            pass

    def _send_stop(self):
        try:
            requests.post("http://127.0.0.1:8080/api/stop", timeout=0.15)
        except:
            pass


# Для тестування окремо
if __name__ == "__main__":
    tracker = YOLOSegmentationTracker()
    tracker.start()