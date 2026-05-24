import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Path

class MissionController(Node):
    def __init__(self):
        super().__init__('mission_controller')
        self.declare_parameter('waypoints', [[0.0,0.0,5.0],[10.0,0.0,5.0]])
        self.waypoints = self.get_parameter('waypoints').get_parameter_value().double_array_value
        self.pose_pub = self.create_publisher(PoseStamped, 'setpoint_position', 10)
        self.path_pub = self.create_publisher(Path, 'mission_path', 10)
        self.timer = self.create_timer(0.2, self.timer_cb)
        self.idx = 0
        self.get_logger().info('MissionController started')

    def timer_cb(self):
        if self.idx >= len(self.waypoints)/3:
            return
        x = self.waypoints[self.idx*3 + 0]
        y = self.waypoints[self.idx*3 + 1]
        z = self.waypoints[self.idx*3 + 2]
        msg = PoseStamped()
        msg.pose.position.x = x
        msg.pose.position.y = y
        msg.pose.position.z = z
        self.pose_pub.publish(msg)
        self.get_logger().info(f'Sending waypoint {self.idx}: {x},{y},{z}')
        self.idx += 1

def main(args=None):
    rclpy.init(args=args)
    node = MissionController()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
