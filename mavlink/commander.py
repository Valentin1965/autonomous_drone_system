from pymavlink import mavutil


class Commander:
    def __init__(self, conn: "MavlinkConnection", logger=None):
        self.conn = conn
        self.logger = logger

    def arm(self):
        if self.logger:
            self.logger.info("Arming...")
        self.conn.arm()

    def disarm(self):
        if self.logger:
            self.logger.info("Disarming...")
        self.conn.disarm()

    def takeoff(self, alt: float = 3.0):
        if self.logger:
            self.logger.info(f"Takeoff to {alt} m...")
        self.conn.send_command_long(
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            [0, 0, 0, 0, 0, 0, alt],
        )

    def land(self):
        if self.logger:
            self.logger.info("Landing...")
        self.conn.send_command_long(
            mavutil.mavlink.MAV_CMD_NAV_LAND,
            [0, 0, 0, 0, 0, 0, 0],
        )
