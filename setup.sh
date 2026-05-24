#!/bin/bash
set -e

WS=$(pwd)
echo "Workspace: $WS"

mkdir -p src
cd src

########################
# drone_mission
########################
ros2 pkg create drone_mission --build-type ament_python --dependencies rclpy geometry_msgs nav_msgs sensor_msgs std_msgs

cat > drone_mission/drone_mission/mission_controller.py << 'EOF'
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
EOF

cat > drone_mission/setup.py << 'EOF'
from setuptools import setup

package_name = 'drone_mission'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/mission.yaml']),
        ('share/' + package_name + '/launch', ['launch/mission.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Valentyn',
    maintainer_email='you@example.com',
    description='Mission controller for autonomous drone',
    entry_points={
        'console_scripts': [
            'mission_controller = drone_mission.mission_controller:main',
        ],
    },
)
EOF

mkdir -p drone_mission/config drone_mission/launch

cat > drone_mission/config/mission.yaml << 'EOF'
waypoints:
  - [0.0, 0.0, 5.0]
  - [10.0, 0.0, 5.0]
  - [10.0, 10.0, 5.0]
  - [0.0, 10.0, 5.0]
EOF

cat > drone_mission/launch/mission.launch.py << 'EOF'
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='drone_mission',
            executable='mission_controller',
            name='mission_controller',
            parameters=['config/mission.yaml']
        ),
    ])
EOF

########################
# drone_rtk
########################
ros2 pkg create drone_rtk --build-type ament_python --dependencies rclpy sensor_msgs std_msgs

cat > drone_rtk/drone_rtk/rtk_monitor.py << 'EOF'
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
EOF

cat > drone_rtk/setup.py << 'EOF'
from setuptools import setup

package_name = 'drone_rtk'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Valentyn',
    maintainer_email='you@example.com',
    description='RTK monitor node',
    entry_points={
        'console_scripts': [
            'rtk_monitor = drone_rtk.rtk_monitor:main',
        ],
    },
)
EOF

########################
# drone_diagnostics
########################
ros2 pkg create drone_diagnostics --build-type ament_python --dependencies rclpy std_msgs diagnostic_msgs

cat > drone_diagnostics/drone_diagnostics/diagnostics_node.py << 'EOF'
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
EOF

cat > drone_diagnostics/setup.py << 'EOF'
from setuptools import setup

package_name = 'drone_diagnostics'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Valentyn',
    maintainer_email='you@example.com',
    description='Diagnostics node for drone',
    entry_points={
        'console_scripts': [
            'drone_diagnostics = drone_diagnostics.diagnostics_node:main',
        ],
    },
)
EOF

########################
# drone_visualizer
########################
ros2 pkg create drone_visualizer --build-type ament_python --dependencies rclpy nav_msgs geometry_msgs

cat > drone_visualizer/drone_visualizer/trajectory_visualizer.py << 'EOF'
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
EOF

cat > drone_visualizer/setup.py << 'EOF'
from setuptools import setup

package_name = 'drone_visualizer'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Valentyn',
    maintainer_email='you@example.com',
    description='Trajectory visualizer for drone',
    entry_points={
        'console_scripts': [
            'trajectory_visualizer = drone_visualizer.trajectory_visualizer:main',
        ],
    },
)
EOF

########################
# drone_sitl (SITL + MAVROS launcher)
########################
ros2 pkg create drone_sitl --build-type ament_python --dependencies rclpy

mkdir -p drone_sitl/launch

cat > drone_sitl/launch/sitl_full.launch.py << 'EOF'
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
import os

def generate_launch_description():
    ld = LaunchDescription()

    # PX4 SITL (приклад, шлях підлаштуєш під свій PX4)
    px4_sitl = ExecuteProcess(
        cmd=['bash', '-c', 'cd ~/PX4-Autopilot && make px4_sitl_default gazebo'],
        output='screen'
    )

    # MAVROS2 (приклад, підлаштувати під твій launch)
    mavros_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            ['/opt/ros/humble/share/mavros/launch/px4.launch.py']
        )
    )

    mission = Node(
        package='drone_mission',
        executable='mission_controller',
        name='mission_controller',
        parameters=['config/mission.yaml'],
        output='screen'
    )

    viz = Node(
        package='drone_visualizer',
        executable='trajectory_visualizer',
        name='trajectory_visualizer',
        output='screen'
    )

    rtk = Node(
        package='drone_rtk',
        executable='rtk_monitor',
        name='rtk_monitor',
        output='screen'
    )

    diag = Node(
        package='drone_diagnostics',
        executable='drone_diagnostics',
        name='drone_diagnostics',
        output='screen'
    )

    ld.add_action(px4_sitl)
    ld.add_action(mavros_launch)
    ld.add_action(mission)
    ld.add_action(viz)
    ld.add_action(rtk)
    ld.add_action(diag)

    return ld
EOF

cat > drone_sitl/setup.py << 'EOF'
from setuptools import setup

package_name = 'drone_sitl'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/sitl_full.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Valentyn',
    maintainer_email='you@example.com',
    description='SITL + MAVROS + full stack launcher',
    entry_points={
        'console_scripts': [],
    },
)
EOF

########################
# Back to workspace root
########################
cd "$WS"

cat > README.md << 'EOF'
# Autonomous Drone System (multi-package ROS2 workspace)

Packages:
- drone_mission
- drone_rtk
- drone_diagnostics
- drone_visualizer
- drone_sitl

## Build

source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash

## Run SITL full stack

ros2 launch drone_sitl sitl_full.launch.py
EOF

echo "Running colcon build..."
source /opt/ros/*/setup.bash || true
colcon build

echo "Done."
EOF
