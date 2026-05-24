import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Path

class TrajectoryVisualizer(Node):
    def __init__(self):
        super().__init__('trajectory_visualizer')
        self.sub = self.create_subscription(PoseStamped, 'setpoint_position', self.cb, 10)
        self.path_pub = self.create_publisher(Path, 'trajectory', 10)
        self.path = Path()
        self.get_logger().info('TrajectoryVisualizer started')

    def cb(self, msg: PoseStamped):
        self.path.header = msg.header
        self.path.poses.append(msg)
        self.path_pub.publish(self.path)

def main(args=None):
    rclpy.init(args=args)
    node = TrajectoryVisualizer()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
