import time
import math
import threading
from pymavlink import mavutil


class PixhawkGPSSimulator:
    def __init__(self, connection_string='udpin:0.0.0.0:14550'):
        self.master = mavutil.mavlink_connection(
            connection_string,
            source_system=1,
            source_component=1
        )
        print(f"Симулятор Pixhawk + GPS запущено на {connection_string}")

        self.lat = 50.4501
        self.lon = 30.5234
        self.alt = 150.0
        self.heading = 90.0
        self.speed = 0.0
        self.target_speed = 1.5
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

        self.recv_thread = threading.Thread(target=self.receive_messages, daemon=True)
        self.recv_thread.start()

        self.cmd_thread = threading.Thread(target=self.command_listener, daemon=True)
        self.cmd_thread.start()

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

        self.master.mav.sys_status_send(
            sensors_present,
            sensors_enabled,
            sensors_health,
            500,
            12000,
            int(self.battery_current * 100),
            self.battery_remaining,
            0, 0, 0, 0
        )

    def send_battery_status(self):
        voltages = [int(self.battery_voltage * 1000)] + [0] * 9
        self.master.mav.bbattery_status_send(
            0,
            mavutil.mavlink.MAV_BATTERY_FUNCTION_ALL,
            mavutil.mavlink.MAV_BATTERY_TYPE_LIPO,
            0,
            voltages,
            int(self.battery_current * 100),
            int(self.battery_voltage * 1000),
            -1,
            self.battery_remaining,
            0, 0, 0
        )

    def send_gps_raw_int(self):
        lat_int = int(self.lat * 1e7)
        lon_int = int(self.lon * 1e7)
        self.master.mav.gps_raw_int_send(
            int(time.time() * 1e6),
            self.fix_type,
            lat_int,
            lon_int,
            int(self.alt * 1000),
            200,
            300,
            int(self.speed * 100),
            int(self.heading * 100),
            self.satellites_visible
        )

    def send_global_position_int(self):
        self.master.mav.global_position_int_send(
            int(time.time() * 1e3),
            int(self.lat * 1e7),
            int(self.lon * 1e7),
            int(self.alt * 1000),
            int(self.alt * 1000),
            int(self.speed * 100),
            0,
            0,
            int(self.heading * 100)
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

                elif msg_type == "COMMAND_LONG":
                    self.handle_command_long(msg)

                elif msg_type == "SET_MODE":
                    self.handle_set_mode(msg)

            except Exception as e:
                print(f"Помилка прийому: {e}")
                time.sleep(0.1)

    def handle_set_position_target(self, msg):
        with self.lock:
            if msg.target_system not in (0, self.master.source_system):
                return

            if msg.coordinate_frame == mavutil.mavlink.MAV_FRAME_GLOBAL_INT:
                self.target_lat = msg.lat_int / 1e7
                self.target_lon = msg.lon_int / 1e7
                self.guided_active = True

                if msg.vx > 0:
                    self.target_speed = msg.vx / 100.0

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
            if self.guided_active and self.target_lat is not None and self.armed:
                bearing = self.calculate_bearing(self.lat, self.lon, self.target_lat, self.target_lon)
                distance = self.haversine_distance(self.lat, self.lon, self.target_lat, self.target_lon)

                if distance < 2.0:
                    self.target_speed = 0.0
                    self.guided_active = False
                    print("✅ Ціль досягнута!")
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

            if self.speed > 0.1:
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
                self.send_sys_status()
                last_sys = t

            if t - last_batt > 2.0:
                self.send_battery_status()
                last_batt = t

            if t - last_gps > 0.1:
                self.update_position(dt=0.1)
                self.send_gps_raw_int()
                self.send_global_position_int()
                last_gps = t

            if int(t) % 2 == 0:
                status = "GUIDED →" if self.guided_active else ""
                print(f"→ {status} Lat: {self.lat:.6f}, Lon: {self.lon:.6f} | Speed: {self.speed:.1f} м/с | Heading: {self.heading:.1f}° | Mode: {self.mode} | Armed: {self.armed}")

            time.sleep(0.01)

    def stop(self):
        self.running = False


if __name__ == "__main__":
    try:
        sim = PixhawkGPSSimulator('udpin:0.0.0.0:14550')
        sim.simulate_movement()
    except KeyboardInterrupt:
        print("\nСимулятор зупинено.")
    finally:
        sim.stop()
