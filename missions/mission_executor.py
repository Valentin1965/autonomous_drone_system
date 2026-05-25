from pymavlink import mavutil
import time


class MissionExecutor:
    def __init__(self, conn: "MavlinkConnection", logger=None):
        self.conn = conn
        self.logger = logger

    def execute_local_mission(self, waypoints):
        m = self.conn.master
        dt = 0.2

        if self.logger:
            self.logger.info("Executing mission from mission.yaml...")

        for wp in waypoints:
            t = wp["type"].upper()
            x, y, z = wp["x"], wp["y"], wp["z"]

            if t in ("TAKEOFF", "WAYPOINT", "LAND"):
                if self.logger:
                    self.logger.info(f"→ Moving to: {t} ({x}, {y}, {z})")

                for _ in range(int(5 / dt)):
                    m.mav.set_position_target_local_ned_send(
                        int(time.time() * 1e3),
                        m.target_system,
                        m.target_component,
                        mavutil.mavlink.MAV_FRAME_LOCAL_NED,
                        0b0000111111111000,
                        x, y, z,
                        0, 0, 0,
                        0, 0, 0,
                        0, 0,
                    )
                    time.sleep(dt)

        if self.logger:
            self.logger.info("Mission finished.")
