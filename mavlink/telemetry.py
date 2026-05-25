class Telemetry:
    def __init__(self, conn: "MavlinkConnection", logger=None):
        self.conn = conn
        self.logger = logger

    def read_attitude(self):
        msg = self.conn.master.recv_match(type="ATTITUDE", blocking=False)
        if msg:
            return msg.roll, msg.pitch, msg.yaw
        return None
