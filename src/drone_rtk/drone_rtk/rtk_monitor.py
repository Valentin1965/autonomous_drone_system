import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix

class RTKMonitor(Node):
    def __init__(self):
        super().__init__('rtk_monitor')
        self.sub = self.create_subscription(NavSatFix, '/rtk/fix', self.cb, 10)
        self.get_logger().info('RTKMonitor started')

    def cb(self, msg: NavSatFix):
        self.get_logger().info(f'RTK: {msg.latitude:.7f}, {msg.longitude:.7f}, status={msg.status.status}')

def main(args=None):
    rclpy.init(args=args)
    node = RTKMonitor()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
