from pymavlink import mavutil
import time


class OffboardController:
    def __init__(self, conn: "MavlinkConnection", rate_hz: float = 20.0, logger=None):
        self.conn = conn
        self.rate_hz = rate_hz
        self.logger = logger

    def _set_offboard_mode(self):
        if self.logger:
            self.logger.info("Switching to OFFBOARD mode...")
        self.conn.set_mode("OFFBOARD")

    def send_position_setpoint_local_ned(self, x, y, z, yaw=0.0):
        m = self.conn.master
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

    def fly_square(self, size=5.0, alt=-3.0, loops=1):
        self._set_offboard_mode()
        m = self.conn.master
        dt = 1.0 / self.rate_hz

        points = [
            (0.0, 0.0, alt),
            (size, 0.0, alt),
            (size, size, alt),
            (0.0, size, alt),
        ] * loops

        if self.logger:
            self.logger.info("Starting OFFBOARD square trajectory...")

        for (x, y, z) in points:
            for _ in range(int(self.rate_hz * 2)):
                self.send_position_setpoint_local_ned(x, y, z)
                time.sleep(dt)

        if self.logger:
            self.logger.info("OFFBOARD trajectory finished.")
