import math
import time
import yaml
import threading
import cv2
import requests
import numpy as np
import os
from pathlib import Path
from flask import Flask, jsonify, request

from pymavlink import mavutil
from ultralytics import YOLO

# ROS 2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
import sensor_msgs_py.point_cloud2 as pc2
from std_msgs.msg import Header

# DepthAI (Oak-D)
import depthai as dai

from utils.logger import setup_logger
from mavlink.connection import MavlinkConnection
from mavlink.commander import Commander
from mavlink.offboard import OffboardController

app = Flask(__name__)
logger = setup_logger("drone_web_panel")

SPRAYER_ACTIVE = False
EMERGENCY_STOP = False

# ====================== POINTCLOUD PUBLISHER ======================
class PointCloudPublisher(Node):
    def __init__(self):
        super().__init__('traversable_pc_pub')
        self.pub = self.create_publisher(PointCloud2, '/traversable_pointcloud', 10)

    def publish(self, points):
        if not points: return
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = "oakd_rgb_optical_frame"
        self.pub.publish(pc2.create_cloud_xyz32(header, points))


# ====================== YOLO SEGMENTATION TRACKER (з адаптацією PIC4SeR) ======================
class YOLOSegmentationTracker:
    def __init__(self):
        self.running = False
        self.thread = None
        self.model = None
        self.device = None
        self.pc_node = None

        self.forward_speed = 0.70
        self.lateral_gain = 0.95
        self.center_tolerance = 0.08      # вужчий коридор — точніше центрування
        self.obstacle_stop_threshold = 0.22

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

        self.pipeline = pipeline
        self.device = dai.Device(pipeline)
        logger.info("Oak-D ініціалізовано (RGB + Depth)")

    def start(self):
        if self.running: return {"status": "already_running"}
        
        self.init_oakd()
        model_path = self.get_best_model_path()
        self.model = YOLO(model_path)
        logger.info(f"YOLOv8-seg завантажено: {model_path}")

        if not rclpy.ok():
            rclpy.init()
        self.pc_node = PointCloudPublisher()

        self.running = True
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()
        return {"status": "started"}

    def get_best_model_path(self):
        if not os.path.exists(MODELS_DIR):
            os.makedirs(MODELS_DIR)
        pt_files = list(Path(MODELS_DIR).glob("*.pt"))
        return str(max(pt_files, key=os.path.getmtime)) if pt_files else "yolov8s-seg.pt"

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        if self.device: self.device.close()
        if self.pc_node: self.pc_node.destroy_node()
        return {"status": "stopped"}

    def _tracking_loop(self):
        global SPRAYER_ACTIVE, EMERGENCY_STOP
        rgb_q = self.device.getOutputQueue("rgb", 4, False)
        depth_q = self.device.getOutputQueue("depth", 4, False)

        while self.running and not EMERGENCY_STOP:
            rgb_msg = rgb_q.get()
            depth_msg = depth_q.get()

            frame = rgb_msg.getCvFrame()
            depth_frame = depth_msg.getFrame()   # в мм

            h, w = frame.shape[:2]
            results = self.model(frame, verbose=False, conf=0.45)

            left_mask = None
            right_mask = None
            obstacle_area = 0.0

            for r in results:
                if not r.masks: continue
                for i, mask_tensor in enumerate(r.masks.data):
                    cls_name = self.model.names[int(r.boxes.cls[i])]
                    mask = (mask_tensor.cpu().numpy() * 255).astype(np.uint8)
                    area = np.sum(mask > 0) / (h * w)

                    if cls_name == "traversable":
                        # Розділяємо на ліву та праву частину
                        mid_x = w // 2
                        left_part = mask[:, :mid_x]
                        right_part = mask[:, mid_x:]

                        if np.sum(left_part) > np.sum(right_part):
                            left_mask = mask
                        else:
                            right_mask = mask
                    elif cls_name == "obstacle":
                        obstacle_area += area

            # Автозупинка
            if obstacle_area > self.obstacle_stop_threshold:
                self._send_stop()
                cv2.putText(frame, "STOP - OBSTACLE!", (50, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0,0,255), 4)
                continue

            # === АДАПТАЦІЯ PIC4SeR: ЦЕНТРУВАННЯ ПО РЯДУ ===
            if left_mask is not None or right_mask is not None:
                center_offset = self.calculate_row_center(left_mask, right_mask, w)
                
                forward = self.forward_speed
                lateral = center_offset * self.lateral_gain

                # Автоматичне вмикання оприскувача
                if abs(center_offset) < 0.15:   # добре вирівняний по ряду
                    if not SPRAYER_ACTIVE:
                        SPRAYER_ACTIVE = True
                        logger.info("Авто-вмикання оприскувача — стабільний рух по ряду")
                else:
                    if SPRAYER_ACTIVE:
                        SPRAYER_ACTIVE = False
                        logger.info("Оприскувач вимкнено — корекція курсу")

                self._send_move(forward, lateral)

                # Візуалізація
                overlay = frame.copy()
                if left_mask is not None:
                    overlay = cv2.addWeighted(overlay, 0.7, cv2.cvtColor(left_mask, cv2.COLOR_GRAY2BGR), 0.3, 0)
                if right_mask is not None:
                    overlay = cv2.addWeighted(overlay, 0.7, cv2.cvtColor(right_mask, cv2.COLOR_GRAY2BGR), 0.3, 0)
                
                cv2.line(overlay, (w//2, 0), (w//2, h), (255, 255, 0), 2)
                cv2.imshow("Vineyard Row Navigation", overlay)

            if cv2.waitKey(1) & 0xFF == 27:
                break

    def calculate_row_center(self, left_mask, right_mask, width):
        """Обчислює зміщення від центру ряду (адаптація PIC4SeR)"""
        left_center = right_center = width / 2

        if left_mask is not None:
            moments = cv2.moments(left_mask)
            if moments["m00"] > 5000:
                left_center = moments["m10"] / moments["m00"]

        if right_mask is not None:
            moments = cv2.moments(right_mask)
            if moments["m00"] > 5000:
                right_center = moments["m10"] / moments["m00"]

        row_center = (left_center + right_center) / 2
        offset = (row_center - width / 2) / (width / 2)   # нормалізовано -1..1
        return offset

    def _send_move(self, forward, lateral):
        try:
            requests.post("http://127.0.0.1:8080/api/move",
                          json={"forward": forward, "lateral": lateral, "yaw": 0}, timeout=0.1)
        except: pass

    def _send_stop(self):
        try:
            requests.post("http://127.0.0.1:8080/api/stop", timeout=0.1)
        except: pass

    def generate_pointcloud(self, depth_frame, mask):
        # (залишаємо як раніше — реальна глибина)
        pass


tracker = YOLOSegmentationTracker()

# ====================== FLASK API ======================
# (API для оприскувача, аварійної зупинки — залишаються як раніше)

@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <title>Дрон — Навігація по Рядах</title>
  <style>body{font-family:Arial;margin:20px;background:#111;color:#eee;}</style>
</head>
<body>
  <h2>Автономна Навігація по Рядах + Оприскувач</h2>
  <button onclick="post('/api/start_tracking')">Запустити Трекер</button>
  <button onclick="post('/api/stop_tracking')">Зупинити Трекер</button>
  <button onclick="toggleSprayer()" id="sprayerBtn">Оприскувач ВИМКНЕНО</button>
  <button onclick="emergencyStop()" style="background:#c22;color:white;">⚠ АВАРІЙНА ЗУПИНКА</button>

  <script>
    let sprayer = false;
    function post(url){ fetch(url,{method:'POST'}).then(r=>r.json()).then(console.log); }
    function toggleSprayer(){
      sprayer = !sprayer;
      document.getElementById('sprayerBtn').textContent = sprayer ? "Оприскувач УВІМКНЕНО" : "Оприскувач ВИМКНЕНО";
      post(sprayer ? '/api/sprayer/on' : '/api/sprayer/off');
    }
    function emergencyStop(){ if(confirm('Аварійна зупинка?')) post('/api/emergency/stop'); }
  </script>
</body>
</html>
    """

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)