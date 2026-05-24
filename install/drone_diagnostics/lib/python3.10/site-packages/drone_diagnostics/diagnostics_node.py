import rclpy
from rclpy.node import Node
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus

class DroneDiagnostics(Node):
    def __init__(self):
        super().__init__('drone_diagnostics')
        self.pub = self.create_publisher(DiagnosticArray, '/drone/diagnostics', 10)
        self.timer = self.create_timer(1.0, self.timer_cb)
        self.get_logger().info('DroneDiagnostics started')

    def timer_cb(self):
        msg = DiagnosticArray()
        st = DiagnosticStatus()
        st.name = 'drone_system'
        st.level = DiagnosticStatus.OK
        st.message = 'OK'
        msg.status.append(st)
        self.pub.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = DroneDiagnostics()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
