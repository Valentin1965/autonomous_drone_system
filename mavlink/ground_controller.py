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
        vehicle_id: Optional[str] = None,
    ):
        self.vehicle_id = vehicle_id
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
        self._last_fc_heartbeat = 0.0
        self._reconnecting = False
        self._heartbeat_timeout = heartbeat_timeout

    def ensure_connected(self) -> None:
        with self._lock:
            if self._connected:
                return
            self.conn.connect()
            self._connected = True
            self._last_fc_heartbeat = time.time()
            self._start_telemetry_thread()
        self._wait_for_gps(timeout=2.0)

    def _disconnect(self) -> None:
        with self._lock:
            self._connected = False
            self.conn.close()

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
            stale = (
                self._last_fc_heartbeat > 0
                and now - self._last_fc_heartbeat > self._heartbeat_timeout * 1.5
            )
            if stale and not self._reconnecting:
                if self._fleet_sim() is None:
                    self._try_reconnect()
                    continue
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
            try:
                msg = self.conn.master.recv_match(blocking=True, timeout=0.4)
            except Exception as e:
                if self.logger:
                    self.logger.warning("MAVLink recv error: %s", e)
                if self._fleet_sim() is None:
                    self._try_reconnect()
                continue
            if msg is None:
                continue
            self._handle_telemetry_msg(msg)

    def _try_reconnect(self) -> None:
        if self._fleet_sim() is not None:
            return
        with self._lock:
            if self._reconnecting:
                return
            self._reconnecting = True
        if self.logger:
            self.logger.warning("MAVLink stale/disconnected — reconnecting…")
        try:
            from simulator import fleet_registry

            if self._fleet_sim() is not None:
                fleet_registry.halt_motion(self.vehicle_id)
            with self._lock:
                self._last_cmd = (0.0, 0.0, 0.0)
            self._disconnect()
            self.conn.connect()
            with self._lock:
                self._connected = True
                self._last_fc_heartbeat = time.time()
            if self.logger:
                self.logger.info("MAVLink reconnected.")
        except Exception as e:
            if self.logger:
                self.logger.error("MAVLink reconnect failed: %s", e)
            with self._lock:
                self._connected = False
        finally:
            with self._lock:
                self._reconnecting = False

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
            src = getattr(msg, "get_srcSystem", lambda: 0)()
            if src and src != 255:
                self._last_fc_heartbeat = time.time()
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

    def _fleet_sim(self):
        from simulator import fleet_registry

        return fleet_registry.get_sim(self.vehicle_id)

    def arm(self) -> None:
        from simulator import fleet_registry

        if self._fleet_sim() is not None:
            fleet_registry.arm_sim(self.vehicle_id)
            with self._lock:
                self._armed = True
            if self.logger:
                self.logger.info("Ground rover ARM (simulator)")
            return
        self.ensure_connected()
        from simulator import fleet_registry

        fleet_registry.arm_sim(self.vehicle_id)
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
        forward = float(forward)
        lateral = float(lateral)
        yaw_rate = float(yaw_rate)

        from simulator import fleet_registry

        applied = fleet_registry.apply_manual_velocity(
            forward, lateral, self._frame, self.vehicle_id
        )
        with self._lock:
            self._last_cmd = (forward, lateral, yaw_rate)

        if self._fleet_sim() is not None and applied:
            if self.logger:
                self.logger.debug(
                    "velocity(sim) fwd=%.2f lat=%.2f", forward, lateral
                )
            return

        self.ensure_connected()
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

        if self.logger:
            self.logger.debug(
                f"velocity frame={self._frame} fwd={forward:.2f} lat={lateral:.2f} yaw={yaw_rate:.2f}"
            )

    def stop(self) -> None:
        from simulator import fleet_registry

        if self._fleet_sim() is not None:
            fleet_registry.halt_motion(self.vehicle_id)
        else:
            self.set_velocity(0.0, 0.0, 0.0)

    def goto_latlon(self, lat: float, lon: float, speed_m_s: float = 1.0, alt_m: float = 0.0) -> None:
        """Навігація до GPS-точки (симулятор / PX4 guided)."""
        self.ensure_connected()
        lat = float(lat)
        lon = float(lon)
        speed_m_s = max(0.1, float(speed_m_s))
        from simulator import fleet_registry

        fleet_registry.set_guided_target(lat, lon, speed_m_s, self.vehicle_id)
        m = self.conn.master
        # Повідомлення з усіма полями (pymavlink 2.4+ вимагає afz, yaw, yaw_rate)
        msg = mavutil.mavlink.MAVLink_set_position_target_global_int_message(
            0,
            m.target_system,
            m.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_INT,
            GLOBAL_GOTO_MASK,
            int(lat * 1e7),
            int(lon * 1e7),
            float(alt_m),
            float(speed_m_s * 100),  # cm/s — симулятор: msg.vx / 100
            0.0,  # vy
            0.0,  # vz
            0.0,  # afx
            0.0,  # afy
            0.0,  # afz
            0.0,  # yaw
            0.0,  # yaw_rate
        )
        m.mav.send(msg)
        if self.logger:
            self.logger.info(f"goto lat={lat:.6f} lon={lon:.6f} speed={speed_m_s:.1f}")

    def get_status(self) -> dict:
        now = time.time()
        from simulator import fleet_registry

        sim_pos = fleet_registry.get_position(self.vehicle_id)
        with self._lock:
            gps = dict(self._telemetry.get("gps") or {})
            hb_age = None
            if self._last_fc_heartbeat > 0:
                hb_age = round(now - self._last_fc_heartbeat, 2)
            connected = self._connected
            gps_source = None
            if sim_pos:
                connected = True
                gps_source = "simulator"
                if not gps.get("lat"):
                    gps = {
                        "lat": float(sim_pos["lat"]),
                        "lon": float(sim_pos["lon"]),
                        "heading": float(sim_pos.get("heading") or 0),
                        "speed": float(sim_pos.get("speed") or 0),
                    }
            elif connected and gps.get("lat") is not None:
                gps_source = "mavlink"
            return {
                "connected": connected,
                "armed": self._armed,
                "frame": self._frame,
                "connection": self.connection_string,
                "vehicle_id": self.vehicle_id,
                "heartbeat_age_s": hb_age,
                "reconnecting": self._reconnecting,
                "gps_source": gps_source,
                "velocity_cmd": {
                    "forward": self._last_cmd[0],
                    "lateral": self._last_cmd[1],
                    "yaw": self._last_cmd[2],
                },
                "gps": gps,
            }
