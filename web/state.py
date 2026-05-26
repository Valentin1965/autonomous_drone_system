"""Thread-safe application state and lazy MAVLink controller."""

import threading
from pathlib import Path

import yaml

from utils.logger import setup_logger

logger = setup_logger("drone_web_panel")


class DroneState:
    def __init__(self):
        self._lock = threading.Lock()
        self._controller = None
        self._cfg = None
        self.sprayer_active = False
        self.emergency_stop = False
        self.mission_waypoints = []  # [{lat, lon}, ...]

    def load_config(self) -> dict:
        if self._cfg is None:
            path = Path(__file__).resolve().parent.parent / "config" / "system.yaml"
            with open(path, "r", encoding="utf-8") as f:
                self._cfg = yaml.safe_load(f)
        return self._cfg

    def get_controller(self):
        if self._controller is None:
            with self._lock:
                if self._controller is None:
                    from mavlink.ground_controller import GroundController

                    from mavlink.runtime_config import client_connection_string

                    cfg = self.load_config()
                    mavlink_cfg = cfg.get("mavlink", {})
                    offboard_cfg = cfg.get("offboard", {})
                    vehicle_cfg = cfg.get("vehicle", {})
                    self._controller = GroundController(
                        connection_string=client_connection_string(cfg),
                        rate_hz=offboard_cfg.get("rate_hz", 20),
                        default_frame=vehicle_cfg.get("default_frame", "body"),
                        heartbeat_timeout=mavlink_cfg.get("heartbeat_timeout", 5),
                        logger=logger,
                    )
        return self._controller


drone_state = DroneState()
