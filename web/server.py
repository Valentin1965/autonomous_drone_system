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

# ====================== ГЛОБАЛЬНІ СТАНИ ======================
SPRAYER_ACTIVE = False
EMERGENCY_STOP = False

# ====================== POINTCLOUD PUBLISHER ======================
class PointCloudPublisher(Node):
    def __init__(self):
        super().__init__('traversable_pointcloud_publisher')
        self.pub = self.create_publisher(PointCloud2, '/traversable_pointcloud', 10)
        logger.info("PointCloud2 Publisher запущено → /traversable_pointcloud")

    def publish(self, points, frame_id="oakd_rgb_optical_frame"):
        if not points:
            return
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = frame_id
        cloud_msg = pc2.create_cloud_xyz32(header, points)
        self.pub.publish(cloud_msg)


# ====================== YOLOv8 SEGMENTATION TRACKER ======================
class YOLOSegmentationTracker:
    def __init__(self):
        self.running = False
        self.thread = None
        self.model = None
        self.device = None
        self.pc_node = None

        self.forward_speed = 0.70
        self.lateral_gain = 0.95
        self.center_tolerance = 0.09      # точне центрування по ряду
        self.obstacle_stop_threshold = 0.24

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
        logger.info("Oak-D (RGB + Depth) ініціалізовано")

    def get_best_model_path(self):
        models_dir = "models"
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)
        pt_files = list(Path(models_dir).glob("*.pt"))
        return str(max(pt_files, key=os.path.getmtime)) if pt_files else "yolov8s-seg.pt"

    def start(self):
        if self.running:
            return {"status": "already_running"}

        self.init_oakd()
        model_path = self.get_best_model_path()
        self.model = YOLO(model_path)
        logger.info(f"YOLOv8-seg модель завантажена: {model_path}")

        if not rclpy.ok():
            rclpy.init()
        self.pc_node = PointCloudPublisher()

        self.running = True
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()
        return {"status": "started"}

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        if self.device:
            self.device.close()
        if self.pc_node:
            self.pc_node.destroy_node()
        return {"status": "stopped"}

    def _tracking_loop(self):
        global SPRAYER_ACTIVE, EMERGENCY_STOP
        rgb_q = self.device.getOutputQueue("rgb", 4, False)
        depth_q = self.device.getOutputQueue("depth", 4, False)

        while self.running and not EMERGENCY_STOP:
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
                            cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0,0,255), 4)
                continue

            # Центрування по ряду (адаптація PIC4SeR)
            offset = self.calculate_center_offset(left_mask, right_mask, w)

            forward = self.forward_speed
            lateral = offset * self.lateral_gain

            # Автоматичне вмикання оприскувача при стабільному русі по ряду
            if abs(offset) < 0.12:
                if not SPRAYER_ACTIVE:
                    SPRAYER_ACTIVE = True
                    self._set_sprayer(True)
            else:
                if SPRAYER_ACTIVE:
                    SPRAYER_ACTIVE = False
                    self._set_sprayer(False)

            self._send_move(forward, lateral)

            # Візуалізація
            overlay = frame.copy()
            if left_mask is not None:
                overlay = cv2.addWeighted(overlay, 0.7, cv2.cvtColor(left_mask, cv2.COLOR_GRAY2BGR), 0.3, 0)
            if right_mask is not None:
                overlay = cv2.addWeighted(overlay, 0.7, cv2.cvtColor(right_mask, cv2.COLOR_GRAY2BGR), 0.3, 0)

            cv2.line(overlay, (w//2, 0), (w//2, h), (0, 255, 255), 2)
            cv2.imshow("Vineyard Navigation", overlay)

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
                          json={"forward": forward, "lateral": lateral, "yaw": 0}, timeout=0.12)
        except:
            pass

    def _send_stop(self):
        try:
            requests.post("http://127.0.0.1:8080/api/stop", timeout=0.12)
        except:
            pass

    def _set_sprayer(self, state: bool):
        endpoint = "/api/sprayer/on" if state else "/api/sprayer/off"
        try:
            requests.post(f"http://127.0.0.1:8080{endpoint}", timeout=0.1)
        except:
            pass


tracker = YOLOSegmentationTracker()

# ====================== FLASK ROUTES ======================
@app.route("/api/start_tracking", methods=["POST"])
def api_start_tracking():
    return jsonify(tracker.start())

@app.route("/api/stop_tracking", methods=["POST"])
def api_stop_tracking():
    return jsonify(tracker.stop())

@app.route("/api/sprayer/on", methods=["POST"])
def api_sprayer_on():
    global SPRAYER_ACTIVE
    SPRAYER_ACTIVE = True
    logger.info("Оприскувач УВІМКНЕНО")
    return jsonify({"sprayer": "on"})

@app.route("/api/sprayer/off", methods=["POST"])
def api_sprayer_off():
    global SPRAYER_ACTIVE
    SPRAYER_ACTIVE = False
    logger.info("Оприскувач ВИМКНЕНО")
    return jsonify({"sprayer": "off"})

@app.route("/api/emergency/stop", methods=["POST"])
def api_emergency_stop():
    global EMERGENCY_STOP
    EMERGENCY_STOP = True
    tracker._send_stop()
    logger.critical("АВАРІЙНА ЗУПИНКА АКТИВОВАНА!")
    return jsonify({"status": "emergency_stop"})

@app.route("/")
def index():
    return """
<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <title>Дрон — Навігація по Рядах</title>
  <style>
    body {font-family:Arial, sans-serif; margin:20px; background:#111; color:#eee;}
    button {padding:14px; margin:8px 0; width:100%; font-size:17px; border-radius:8px;}
    .sprayer-on {background:#0a0; color:white;}
    .sprayer-off {background:#a00; color:white;}
    .emergency {background:#c22; color:white; font-weight:bold;}
  </style>
</head>
<body>
  <h2>Автономна Навігація по Винограднику</h2>
  
  <button onclick="post('/api/start_tracking')">▶ Запустити YOLO Трекер</button>
  <button onclick="post('/api/stop_tracking')">■ Зупинити Трекер</button>
  
  <hr>
  <h3>Оприскувач</h3>
  <button id="sprayerBtn" onclick="toggleSprayer()" class="sprayer-off">Оприскувач ВИМКНЕНО</button>

  <h3>Аварійне керування</h3>
  <button onclick="emergencyStop()" class="emergency">⚠ АВАРІЙНА ЗУПИНКА ДВИГУНІВ</button>

  <script>
    let sprayer = false;
    function post(url) {
      fetch(url, {method:'POST'}).then(r=>r.json()).then(console.log);
    }
    function toggleSprayer() {
      sprayer = !sprayer;
      const btn = document.getElementById('sprayerBtn');
      btn.textContent = sprayer ? "Оприскувач УВІМКНЕНО" : "Оприскувач ВИМКНЕНО";
      btn.classList.toggle('sprayer-on', sprayer);
      btn.classList.toggle('sprayer-off', !sprayer);
      post(sprayer ? '/api/sprayer/on' : '/api/sprayer/off');
    }
    function emergencyStop() {
      if(confirm("УВАГА! Аварійна зупинка двигунів?")) {
        post('/api/emergency/stop');
      }
    }
  </script>
</body>
</html>
    """

if __name__ == "__main__":
    print("=== Автономна система дрона запущена ===")
    print("YOLOv8 Segmentation + PointCloud2 + Авто-оприскувач")
    app.run(host="0.0.0.0", port=8080, debug=False)