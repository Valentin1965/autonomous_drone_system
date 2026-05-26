import os
import time
import math
import threading
from pymavlink import mavutil


class PixhawkGPSSimulator:
    def __init__(
        self,
        connection_string='udpin:0.0.0.0:14550',
        interactive=None,
        start_lat=None,
        start_lon=None,
        mavlink_system_id=1,
    ):
        self.mavlink_system_id = int(mavlink_system_id)
        self.master = mavutil.mavlink_connection(
            connection_string,
            source_system=self.mavlink_system_id,
            source_component=1
        )
        print(f"Симулятор Pixhawk + GPS запущено на {connection_string}")

        self.lat = float(start_lat) if start_lat is not None else 50.4501
        self.lon = float(start_lon) if start_lon is not None else 30.5234
        self.alt = 150.0
        self.heading = 90.0
        self.speed = 0.0
        self.target_speed = 0.0
        self.target_heading = self.heading

        self.target_lat = None
        self.target_lon = None
        self.guided_active = False

        self.satellites_visible = 12
        self.fix_type = 3
        self.armed = False
        self.mode = "MANUAL"

        self.battery_voltage = 12.6
        self.battery_current = 1.2
        self.battery_remaining = 95

        self.running = True
        self.lock = threading.Lock()
        self._boot_mono = time.monotonic()

        self.recv_thread = threading.Thread(target=self.receive_messages, daemon=True)
        self.recv_thread.start()

        if interactive is None:
            interactive = os.environ.get("DRONE_SIM_INTERACTIVE", "0").lower() in (
                "1", "true", "yes",
            )
        self.cmd_thread = None
        if interactive:
            self.cmd_thread = threading.Thread(target=self.command_listener, daemon=True)
            self.cmd_thread.start()

    def _time_boot_ms(self) -> int:
        """MAVLink uint32 ms since boot — not Unix epoch."""
        return int((time.monotonic() - self._boot_mono) * 1000) & 0xFFFFFFFF

    def _time_usec(self) -> int:
        return int((time.monotonic() - self._boot_mono) * 1_000_000) & 0xFFFFFFFFFFFFFFFF

    def _heading_cdeg(self) -> int:
        h = int(self.heading * 100) % 36000
        return max(0, min(65535, h))

    def send_heartbeat(self):
        base_mode = 0
        if self.armed:
            base_mode |= mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        if self.mode == "GUIDED":
            base_mode |= mavutil.mavlink.MAV_MODE_FLAG_GUIDED_ENABLED
        else:
            base_mode |= mavutil.mavlink.MAV_MODE_FLAG_MANUAL_INPUT_ENABLED

        self.master.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GROUND_ROVER,
            mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
            base_mode,
            0,
            mavutil.mavlink.MAV_STATE_ACTIVE
        )

    def send_sys_status(self):
        sensors_present = 0
        sensors_enabled = 0
        sensors_health = 0

        # pymavlink 2.4.x: errors_count1..4 required; battery_remaining = int %
        self.master.mav.sys_status_send(
            int(sensors_present),
            int(sensors_enabled),
            int(sensors_health),
            500,
            12000,
            int(self.battery_current * 100),
            int(round(self.battery_remaining)),
            0,
            0,
            0,
            0,
            0,
            0,
        )

    def send_battery_status(self):
        """BATTERY_STATUS — pymavlink 2.4.x expects 10 positional args."""
        voltages = [int(self.battery_voltage * 1000)] + [0] * 9
        self.master.mav.battery_status_send(
            0,
            mavutil.mavlink.MAV_BATTERY_FUNCTION_ALL,
            mavutil.mavlink.MAV_BATTERY_TYPE_LIPO,
            0,
            voltages,
            int(self.battery_current * 100),
            -1,
            -1,
            int(self.battery_remaining),
        )

    def send_gps_raw_int(self):
        lat_int = int(self.lat * 1e7)
        lon_int = int(self.lon * 1e7)
        spd = max(-32768, min(32767, int(self.speed * 100)))
        self.master.mav.gps_raw_int_send(
            self._time_usec(),
            self.fix_type,
            lat_int,
            lon_int,
            int(self.alt * 1000),
            200,
            300,
            spd,
            self._heading_cdeg(),
            self.satellites_visible,
        )

    def send_global_position_int(self):
        alt_mm = int(self.alt * 1000)
        hdg_rad = math.radians(self.heading)
        # vx/vy — см/с у NED (північ / схід)
        vx_cm = int(self.speed * 100 * math.cos(hdg_rad))
        vy_cm = int(self.speed * 100 * math.sin(hdg_rad))
        vx_cm = max(-32768, min(32767, vx_cm))
        vy_cm = max(-32768, min(32767, vy_cm))
        self.master.mav.global_position_int_send(
            self._time_boot_ms(),
            int(self.lat * 1e7),
            int(self.lon * 1e7),
            alt_mm,
            alt_mm,
            vx_cm,
            vy_cm,
            0,
            self._heading_cdeg(),
        )

    def receive_messages(self):
        print("Слухач MAVLink команд запущено...")
        while self.running:
            try:
                msg = self.master.recv_match(blocking=False, timeout=0.01)
                if not msg:
                    continue

                msg_type = msg.get_type()

                if msg_type == "SET_POSITION_TARGET_GLOBAL_INT":
                    self.handle_set_position_target(msg)

                elif msg_type == "SET_POSITION_TARGET_LOCAL_NED":
                    self.handle_set_position_target_local_ned(msg)

                elif msg_type == "COMMAND_LONG":
                    self.handle_command_long(msg)

                elif msg_type == "SET_MODE":
                    self.handle_set_mode(msg)

            except Exception as e:
                print(f"Помилка прийому: {e}")
                time.sleep(0.1)

    def handle_set_position_target_local_ned(self, msg):
        """Velocity or position setpoints in LOCAL_NED / BODY_NED (rover)."""
        with self.lock:
            if not self._accept_target(int(msg.target_system)):
                return

            vx = float(msg.vx)
            vy = float(msg.vy)
            speed = math.hypot(vx, vy)

            if speed < 0.02:
                self.target_speed = 0.0
                return

            frame = msg.coordinate_frame
            if frame == mavutil.mavlink.MAV_FRAME_BODY_NED:
                heading_rad = math.radians(self.heading)
                vn = vx * math.cos(heading_rad) - vy * math.sin(heading_rad)
                ve = vx * math.sin(heading_rad) + vy * math.cos(heading_rad)
                self.target_heading = math.degrees(math.atan2(ve, vn)) % 360
            else:
                self.target_heading = math.degrees(math.atan2(vy, vx)) % 360

            self.target_speed = min(2.5, max(0.0, speed))
            self.guided_active = True
            if not self.armed:
                self.armed = True
            self.mode = "GUIDED"
            print(
                f"→ SET_POSITION_TARGET_LOCAL_NED: vx={vx:.2f} vy={vy:.2f} "
                f"→ speed={self.target_speed:.2f} hdg={self.target_heading:.1f}°"
            )

    def _accept_target(self, target_system: int) -> bool:
        """GCS (255), broadcast (0), або system id цього симулятора."""
        if target_system in (0, 255):
            return True
        return target_system in (1, self.mavlink_system_id, self.master.source_system)

    def handle_set_position_target(self, msg):
        with self.lock:
            if not self._accept_target(int(msg.target_system)):
                return

            if msg.coordinate_frame == mavutil.mavlink.MAV_FRAME_GLOBAL_INT:
                lat_raw = getattr(msg, "lat_int", None)
                if lat_raw is None:
                    lat_raw = msg.lat
                lon_raw = getattr(msg, "lon_int", None)
                if lon_raw is None:
                    lon_raw = msg.lon
                self.target_lat = lat_raw / 1e7
                self.target_lon = lon_raw / 1e7
                self.guided_active = True

                if msg.vx > 0:
                    self.target_speed = msg.vx / 100.0
                elif self.target_speed < 0.1:
                    self.target_speed = 1.0

                print(f"→ SET_POSITION_TARGET_GLOBAL_INT: Lat={self.target_lat:.6f}, Lon={self.target_lon:.6f}, Speed={self.target_speed:.1f} м/с")

                if not self.armed:
                    self.armed = True
                self.mode = "GUIDED"

    def handle_command_long(self, msg):
        with self.lock:
            if msg.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
                if msg.param1 == 1:
                    self.armed = True
                    print("→ ARM (COMMAND_LONG)")
                else:
                    self.armed = False
                    self.target_speed = 0.0
                    self.guided_active = False
                    print("→ DISARM (COMMAND_LONG)")

            elif msg.command == mavutil.mavlink.MAV_CMD_DO_SET_MODE:
                base_mode = int(msg.param1)
                custom_mode = int(msg.param2)
                print(f"→ DO_SET_MODE: base_mode={base_mode}, custom_mode={custom_mode}")
                if base_mode & mavutil.mavlink.MAV_MODE_FLAG_GUIDED_ENABLED:
                    self.mode = "GUIDED"
                    self.guided_active = True
                else:
                    self.mode = "MANUAL"
                    self.guided_active = False

    def handle_set_mode(self, msg):
        with self.lock:
            base_mode = msg.base_mode
            custom_mode = msg.custom_mode
            print(f"→ SET_MODE: base_mode={base_mode}, custom_mode={custom_mode}")
            if base_mode & mavutil.mavlink.MAV_MODE_FLAG_GUIDED_ENABLED:
                self.mode = "GUIDED"
                self.guided_active = True
            else:
                self.mode = "MANUAL"
                self.guided_active = False

    def calculate_bearing(self, lat1, lon1, lat2, lon2):
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlon = lon2 - lon1
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        bearing = math.degrees(math.atan2(y, x))
        return (bearing + 360) % 360

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        R = 6378137.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c

    def update_position(self, dt=0.1):
        with self.lock:
            # Ручний rух: цільова швидкість без GPS-waypoint
            if (
                self.guided_active
                and self.target_lat is None
                and self.armed
                and self.target_speed > 0.05
            ):
                pass
            elif self.guided_active and self.target_lat is not None and self.armed:
                bearing = self.calculate_bearing(
                    self.lat, self.lon, self.target_lat, self.target_lon
                )
                distance = self.haversine_distance(
                    self.lat, self.lon, self.target_lat, self.target_lon
                )
                arrival_m = 2.5

                if distance <= arrival_m:
                    self.target_speed = 0.0
                    self.speed = 0.0
                    self.target_lat = None
                    self.target_lon = None
                    self.guided_active = False
                else:
                    self.target_heading = bearing
                    self.target_speed = min(2.5, max(0.5, distance / 5))

            if self.speed < self.target_speed:
                self.speed = min(self.target_speed, self.speed + 1.2 * dt)
            elif self.speed > self.target_speed:
                self.speed = max(self.target_speed, self.speed - 2.0 * dt)

            diff = (self.target_heading - self.heading + 180) % 360 - 180
            self.heading += diff * 1.2 * dt
            self.heading %= 360

            # Рух за цільовою швидкістю (velocity setpoint або guided waypoint)
            if self.armed and self.target_speed > 0.05:
                if self.speed < 0.05:
                    self.speed = min(self.target_speed, 0.15)

            # Рух лише в GUIDED до цільової точки (не дрейф у MANUAL)
            if self.guided_active and self.speed > 0.05:
                dist = self.speed * dt
                br_rad = math.radians(self.heading)
                R = 6378137.0
                self.lat += (dist * math.cos(br_rad)) / R * (180 / math.pi)
                self.lon += (dist * math.sin(br_rad)) / (R * math.cos(math.radians(self.lat))) * (180 / math.pi)

            self.battery_remaining = max(0, self.battery_remaining - 0.001 * self.speed)

    def command_listener(self):
        print("\nКоманди:")
        print("  speed <м/с>     heading <°>     arm / disarm")
        print("  mode <MANUAL/GUIDED>     status     quit")
        while self.running:
            try:
                cmd = input(">>> ").strip().lower()
                if not cmd:
                    continue
                parts = cmd.split()
                action = parts[0]

                with self.lock:
                    if action == "speed" and len(parts) > 1:
                        self.target_speed = max(0.0, float(parts[1]))
                    elif action == "heading" and len(parts) > 1:
                        self.target_heading = float(parts[1]) % 360
                    elif action == "arm":
                        self.armed = True
                    elif action == "disarm":
                        self.armed = False
                        self.target_speed = 0.0
                        self.guided_active = False
                    elif action == "mode" and len(parts) > 1:
                        self.mode = parts[1].upper()
                        if self.mode == "GUIDED":
                            self.guided_active = True
                    elif action == "status":
                        print(f"Lat: {self.lat:.6f}, Lon: {self.lon:.6f} | Speed: {self.speed:.1f} | Mode: {self.mode} | Armed: {self.armed} | Batt: {self.battery_remaining:.1f}%")
                    elif action == "quit":
                        self.running = False
                        break
            except Exception as e:
                print(f"Помилка: {e}")

    def simulate_movement(self):
        print("Симуляція запущена (вигляд реального Rover для QGC)")
        last_heartbeat = 0
        last_gps = 0
        last_sys = 0
        last_batt = 0

        while self.running:
            t = time.time()

            if t - last_heartbeat > 1.0:
                self.send_heartbeat()
                last_heartbeat = t

            if t - last_sys > 1.0:
                try:
                    self.send_sys_status()
                except TypeError as e:
                    print(f"⚠ sys_status_send: {e}")
                last_sys = t

            if t - last_batt > 2.0:
                try:
                    self.send_battery_status()
                except TypeError as e:
                    print(f"⚠ battery_status_send: {e}")
                last_batt = t

            if t - last_gps > 0.1:
                self.update_position(dt=0.1)
                try:
                    self.send_gps_raw_int()
                    self.send_global_position_int()
                except TypeError as e:
                    print(f"⚠ GPS send: {e}")
                last_gps = t

            if int(t) % 5 == 0 and int(t) != getattr(self, "_last_print_t", -1):
                self._last_print_t = int(t)
                status = "GUIDED →" if self.guided_active else ""
                print(
                    f"→ {status} Lat: {self.lat:.6f}, Lon: {self.lon:.6f} | "
                    f"Speed: {self.speed:.1f} м/с | Heading: {self.heading:.1f}° | "
                    f"Mode: {self.mode} | Armed: {self.armed}"
                )

            time.sleep(0.01)

    def stop(self):
        self.running = False

    def get_position(self) -> dict:
        with self.lock:
            return {
                "lat": self.lat,
                "lon": self.lon,
                "heading": self.heading,
                "speed": self.speed,
                "battery_pct": round(self.battery_remaining, 1),
                "armed": self.armed,
                "mode": self.mode,
            }


if __name__ == "__main__":
    try:
        sim = PixhawkGPSSimulator('udpin:0.0.0.0:14550')
        sim.simulate_movement()
    except KeyboardInterrupt:
        print("\nСимулятор зупинено.")
    finally:
        sim.stop()
