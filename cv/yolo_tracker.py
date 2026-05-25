# cv/yolov8_tracker.py
import cv2
import numpy as np
import threading
import time
import requests
from pathlib import Path
from ultralytics import YOLO
import depthai as dai

class YOLOV8Tracker:
    def __init__(self, config):
        self.config = config
        self.running = False
        self.thread = None
        self.model = None
        self.device = None  # Oak-D device

        self.sprayer_active = False
        self.emergency_stop = False

        self.forward_speed = 0.70
        self.lateral_gain = 0.92
        self.center_tolerance = 0.10

    def load_model(self):
        model_path = self.config.get("yolo_model", "models/vineyard_seg.pt")
        self.model = YOLO(model_path)
        print(f"[CV] YOLOv8-seg модель завантажена: {model_path}")

    def start(self):
        if self.running:
            return False
        self.load_model()
        self.running = True
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()
        print("[CV] Трекер запущено")
        return True

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)
        print("[CV] Трекер зупинено")

    def _tracking_loop(self):
        # Ініціалізація Oak-D
        pipeline = dai.Pipeline()
        # ... (твій код ініціалізації Oak-D RGB + Depth)

        rgb_q = self.device.getOutputQueue("rgb", 4, False)
        depth_q = self.device.getOutputQueue("depth", 4, False)

        while self.running and not self.emergency_stop:
            rgb_frame = rgb_q.get().getCvFrame()
            depth_frame = depth_q.get().getFrame()

            results = self.model(rgb_frame, verbose=False, conf=0.45)

            left_mask = right_mask = None
            obstacle_area = 0.0

            for r in results:
                if not r.masks: continue
                for i, mask_t in enumerate(r.masks.data):
                    cls_name = self.model.names[int(r.boxes.cls[i])]
                    mask = (mask_t.cpu().numpy() * 255).astype(np.uint8)
                    area = np.sum(mask > 0) / (rgb_frame.shape[0] * rgb_frame.shape[1])

                    if cls_name == "traversable":
                        mid = rgb_frame.shape[1] // 2
                        if np.sum(mask[:, :mid]) > np.sum(mask[:, mid:]):
                            left_mask = mask
                        else:
                            right_mask = mask
                    elif cls_name == "obstacle":
                        obstacle_area += area

            # Автозупинка
            if obstacle_area > 0.22:
                self._send_stop()
                continue

            # Центрування по ряду (адаптація PIC4SeR)
            offset = self.calculate_center_offset(left_mask, right_mask, rgb_frame.shape[1])
            
            forward = self.forward_speed
            lateral = offset * self.lateral_gain

            # Авто-вмикання оприскувача
            if abs(offset) < 0.12:
                if not self.sprayer_active:
                    self.sprayer_active = True
                    self._set_sprayer(True)
            else:
                if self.sprayer_active:
                    self.sprayer_active = False
                    self._set_sprayer(False)

            self._send_move(forward, lateral)

    def calculate_center_offset(self, left, right, width):
        """Центрування по лівій та правій стіні ряду"""
        left_c = right_c = width / 2
        if left is not None:
            m = cv2.moments(left)
            if m["m00"] > 5000:
                left_c = m["m10"] / m["m00"]
        if right is not None:
            m = cv2.moments(right)
            if m["m00"] > 5000:
                right_c = m["m10"] / m["m00"]
        center = (left_c + right_c) / 2
        return (center - width/2) / (width/2)

    def _send_move(self, forward, lateral):
        requests.post("http://127.0.0.1:8080/api/move", 
                      json={"forward": forward, "lateral": lateral, "yaw": 0}, timeout=0.1)

    def _send_stop(self):
        requests.post("http://127.0.0.1:8080/api/stop", timeout=0.1)

    def _set_sprayer(self, state: bool):
        endpoint = "/api/sprayer/on" if state else "/api/sprayer/off"
        requests.post(f"http://127.0.0.1:8080{endpoint}", timeout=0.1)