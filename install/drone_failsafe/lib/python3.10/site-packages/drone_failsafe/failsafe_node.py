import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState, NavSatFix
from diagnostic_msgs.msg import DiagnosticStatus
from mavros_msgs.srv import CommandLong
from mavros_msgs.msg import State
import time

class DroneFailsafe(Node):
    def __init__(self):
        super().__init__('drone_failsafe')

        # Battery
        self.create_subscription(BatteryState, '/mavros/battery', self.battery_cb, 10)

        # GPS
        self.create_subscription(NavSatFix, '/mavros/global_position/raw/fix', self.gps_cb, 10)

        # PX4 state
        self.create_subscription(State, '/mavros/state', self.state_cb, 10)

        # RTL service
        self.rtl_client = self.create_client(CommandLong, '/mavros/cmd/command')

        self.low_battery_threshold = 0.20
        self.last_gps_time = time.time()
        self.last_heartbeat_time = time.time()

        self.timer = self.create_timer(1.0, self.timer_cb)

        self.get_logger().info("Failsafe module started")

    def battery_cb(self, msg: BatteryState):
        if msg.percentage < self.low_battery_threshold:
            self.get_logger().warn(f"LOW BATTERY: {msg.percentage:.2f}")
            self.trigger_rtl("Low battery")

    def gps_cb(self, msg: NavSatFix):
        if msg.status.status < 0:
            self.get_logger().warn("GPS LOST")
            self.trigger_rtl("GPS lost")
        self.last_gps_time = time.time()

    def state_cb(self, msg: State):
        if not msg.connected:
            self.get_logger().warn("PX4 disconnected")
            self.trigger_rtl("PX4 disconnected")

    def timer_cb(self):
        # GPS timeout
        if time.time() - self.last_gps_time > 5:
            self.get_logger().warn("GPS TIMEOUT")
            self.trigger_rtl("GPS timeout")

    def trigger_rtl(self, reason):
        self.get_logger().error(f"FAILSAFE TRIGGERED: {reason}")

        if not self.rtl_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().error("RTL service unavailable")
            return

        req = CommandLong.Request()
        req.command = 20  # MAV_CMD_NAV_RETURN_TO_LAUNCH
        req.confirmation = 0
        req.param1 = 0

        self.rtl_client.call_async(req)

def main(args=None):
    rclpy.init(args=args)
    node = DroneFailsafe()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
