from pymavlink import mavutil


class MavlinkConnection:
    def __init__(self, connection_string: str, heartbeat_timeout: float = 5.0, logger=None):
        self.connection_string = connection_string
        self.heartbeat_timeout = heartbeat_timeout
        self.master = None
        self.logger = logger

    def close(self) -> None:
        if self.master is not None:
            try:
                self.master.close()
            except Exception:
                pass
            self.master = None

    def connect(self):
        self.close()
        if self.logger:
            self.logger.info(f"Connecting to MAVLink on {self.connection_string}...")
        self.master = mavutil.mavlink_connection(
            self.connection_string,
            source_system=255,
            source_component=190,
        )
        # UDP: симулятор дізнається адресу GCS лише після вхідного пакета
        self.master.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0,
            0,
            mavutil.mavlink.MAV_STATE_ACTIVE,
        )
        self.master.wait_heartbeat(timeout=self.heartbeat_timeout)
        if self.logger:
            self.logger.info("Heartbeat received. MAVLink connected.")

    def set_mode(self, mode_name: str):
        mode = self.master.mode_mapping()[mode_name]
        self.master.mav.set_mode_send(
            self.master.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode,
        )

    def arm(self):
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1, 0, 0, 0, 0, 0, 0,
        )

    def disarm(self):
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0, 0, 0, 0, 0, 0, 0,
        )

    def send_command_long(self, command, params):
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            command,
            0,
            *params,
        )
