"""
Ground rover control via MAVLink velocity setpoints (LOCAL_NED / BODY_NED).
"""

import math
import threading
import time
from typing import Optional, Tuple

from pymavlink import mavutil

from mavlink.connection import MavlinkConnection
from mavlink.commander import Commander

# Ignore position & accel; use velocity + yaw_rate (PX4 offboard-style)
VELOCITY_TYPE_MASK = 0b0000111111000111

# Lat/lon + vx=speed (cm/s); sim ignores vy/vz/yaw
GLOBAL_GOTO_MASK = (
    mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE
    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE
    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE
    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE
    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
    | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
)


class GroundController:
    def __init__(
        self,
        connection_string: str = "udp:127.0.0.1:14550",
        rate_hz: float = 20.0,
        default_frame: str = "body",
        heartbeat_timeout: float = 5.0,
        logger=None,
    ):
        self.connection_string = connection_string
        self.rate_hz = rate_hz
        self.default_frame = default_frame if default_frame in ("earth", "body") else "body"
        self.logger = logger

        self.conn = MavlinkConnection(connection_string, heartbeat_timeout, logger)
        self.commander = Commander(self.conn, logger)

        self._lock = threading.Lock()
        self._connected = False
        self._armed = False
        self._frame = self.default_frame
        self._last_cmd: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._telemetry: dict = {}
        self._telemetry_stop = threading.Event()
        self._telemetry_thread: Optional[threading.Thread] = None
        self._last_gcs_heartbeat = 0.0

    def ensure_connected(self) -> None:
        with self._lock:
            if self._connected:
                return
            self.conn.connect()
            self._connected = True
            self._start_telemetry_thread()
        self._wait_for_gps(timeout=2.0)

    def _start_telemetry_thread(self) -> None:
        if self._telemetry_thread and self._telemetry_thread.is_alive():
            return
        self._telemetry_stop.clear()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_loop,
            name="mavlink-telemetry",
            daemon=True,
        )
        self._telemetry_thread.start()

    def _telemetry_loop(self) -> None:
        """Постійне читання GPS/heartbeat — не залежить від частоти HTTP poll."""
        while not self._telemetry_stop.is_set():
            if not self._connected or not self.conn.master:
                time.sleep(0.1)
                continue
            now = time.time()
            if now - self._last_gcs_heartbeat > 1.0:
                m = self.conn.master
                m.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0,
                    0,
                    mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                self._last_gcs_heartbeat = now
            msg = self.conn.master.recv_match(blocking=True, timeout=0.4)
            if msg is None:
                continue
            self._handle_telemetry_msg(msg)

    def _wait_for_gps(self, timeout: float = 3.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                gps = self._telemetry.get("gps")
                if gps and gps.get("lat") is not None:
                    return
            time.sleep(0.05)

    def _handle_telemetry_msg(self, msg) -> None:
        t = msg.get_type()
        if t == "HEARTBEAT":
            with self._lock:
                self._armed = bool(
                    msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                )
        elif t == "GPS_RAW_INT":
            hdg = (
                msg.hdg / 100.0
                if msg.hdg != 65535
                else self._telemetry.get("gps", {}).get("heading", 0.0)
            )
            with self._lock:
                self._telemetry["gps"] = {
                    "lat": msg.lat / 1e7,
                    "lon": msg.lon / 1e7,
                    "heading": hdg,
                    "speed": msg.vel / 100.0,
                }
        elif t == "GLOBAL_POSITION_INT":
            with self._lock:
                self._telemetry["gps"] = {
                    "lat": msg.lat / 1e7,
                    "lon": msg.lon / 1e7,
                    "heading": msg.hdg / 100.0 if msg.hdg != 65535 else 0.0,
                    "speed": math.hypot(msg.vx, msg.vy) / 100.0,
                }

    @property
    def frame(self) -> str:
        return self._frame

    def set_frame(self, mode: str) -> None:
        mode = (mode or "").lower()
        if mode not in ("earth", "body"):
            raise ValueError("frame must be 'earth' or 'body'")
        with self._lock:
            self._frame = mode

    def arm(self) -> None:
        self.ensure_connected()
        self.commander.arm()
        with self._lock:
            self._armed = True
        if self.logger:
            self.logger.info("Ground rover ARM sent")

    def disarm(self) -> None:
        self.ensure_connected()
        self.stop()
        self.commander.disarm()
        with self._lock:
            self._armed = False
        if self.logger:
            self.logger.info("Ground rover DISARM sent")

    def set_velocity(self, forward: float, lateral: float, yaw_rate: float = 0.0) -> None:
        """forward/lateral in m/s; yaw_rate in rad/s."""
        self.ensure_connected()
        forward = float(forward)
        lateral = float(lateral)
        yaw_rate = float(yaw_rate)

        if self._frame == "body":
            coord = mavutil.mavlink.MAV_FRAME_BODY_NED
        else:
            coord = mavutil.mavlink.MAV_FRAME_LOCAL_NED

        m = self.conn.master
        m.mav.set_position_target_local_ned_send(
            0,
            m.target_system,
            m.target_component,
            coord,
            VELOCITY_TYPE_MASK,
            0.0, 0.0, 0.0,
            forward, lateral, 0.0,
            0.0, 0.0, 0.0,
            0.0, yaw_rate,
        )

        with self._lock:
            self._last_cmd = (forward, lateral, yaw_rate)

        if self.logger:
            self.logger.debug(
                f"velocity frame={self._frame} fwd={forward:.2f} lat={lateral:.2f} yaw={yaw_rate:.2f}"
            )

    def stop(self) -> None:
        self.set_velocity(0.0, 0.0, 0.0)

    def goto_latlon(self, lat: float, lon: float, speed_m_s: float = 1.0, alt_m: float = 0.0) -> None:
        """Навігація до GPS-точки (симулятор / PX4 guided)."""
        self.ensure_connected()
        lat = float(lat)
        lon = float(lon)
        speed_m_s = max(0.1, float(speed_m_s))
        m = self.conn.master
        m.mav.set_position_target_global_int_send(
            0,
            m.target_system,
            m.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_INT,
            GLOBAL_GOTO_MASK,
            int(lat * 1e7),
            int(lon * 1e7),
            float(alt_m),
            int(speed_m_s * 100),
            0,
            0,
            0.0,
            0.0,
        )
        if self.logger:
            self.logger.info(f"goto lat={lat:.6f} lon={lon:.6f} speed={speed_m_s:.1f}")

    def get_status(self) -> dict:
        with self._lock:
            gps = dict(self._telemetry.get("gps") or {})
            return {
                "connected": self._connected,
                "armed": self._armed,
                "frame": self._frame,
                "connection": self.connection_string,
                "velocity_cmd": {
                    "forward": self._last_cmd[0],
                    "lateral": self._last_cmd[1],
                    "yaw": self._last_cmd[2],
                },
                "gps": gps,
            }
