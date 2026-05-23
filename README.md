#!/bin/bash
set -e

echo "=== Creating GitHub-ready repository ==="

mkdir -p autonomous_drone_system
cd autonomous_drone_system

echo "=== Creating ROS2 workspace ==="
mkdir -p src
cd src

echo "=== Creating ROS2 package ==="
ros2 pkg create autonomous_drone_cv --build-type ament_python
cd autonomous_drone_cv

echo "=== Writing package.xml ==="
cat > package.xml << 'EOF'
<?xml version="1.0"?>
<package format="3">
  <name>autonomous_drone_cv</name>
  <version>0.1.0</version>
  <description>Autonomous drone mission controller with RTK, Pixhawk, trajectory visualization</description>
  <maintainer email="you@example.com">Valentyn</maintainer>
  <license>MIT</license>
  <buildtool_depend>ament_python</buildtool_depend>
  <exec_depend>rclpy</exec_depend>
  <exec_depend>nav_msgs</exec_depend>
  <exec_depend>geometry_msgs</exec_depend>
  <exec_depend>sensor_msgs</exec_depend>
  <exec_depend>mavros_msgs</exec_depend>
  <exec_depend>python3-yaml</exec_depend>
</package>
EOF

echo "=== Writing setup.py ==="
cat > setup.py << 'EOF'
from setuptools import setup

package_name = 'autonomous_drone_cv'

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
    install_requires=['setuptools', 'pyyaml'],
    zip_safe=True,
    maintainer='Valentyn',
    maintainer_email='you@example.com',
    description='Autonomous drone mission controller with RTK, Pixhawk, trajectory visualization',
    entry_points={
        'console_scripts': [
            'mission_controller = autonomous_drone_cv.mission_controller:main',
            'trajectory_visualizer = autonomous_drone_cv.trajectory_visualizer:main',
        ],
    },
)
EOF

echo "=== Creating directories ==="
mkdir -p autonomous_drone_cv
mkdir -p config
mkdir -p launch
mkdir -p resource

echo "=== Writing mission.yaml ==="
cat > config/mission.yaml << 'EOF'
mission:
  waypoints:
    - [0.0, 0.0, 5.0]
    - [10.0, 0.0, 5.0]
    - [10.0, 10.0, 5.0]
    - [0.0, 10.0, 5.0]
  waypoint_tolerance: 0.5
  offboard_rate: 10.0
EOF

echo "=== Writing mission.launch.py ==="
cat > launch/mission.launch.py << 'EOF'
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='autonomous_drone_cv',
            executable='mission_controller',
            name='mission_controller',
            parameters=['config/mission.yaml']
        ),
        Node(
            package='autonomous_drone_cv',
            executable='trajectory_visualizer',
            name='trajectory_visualizer'
        )
    ])
EOF

echo "=== Writing mission_controller.py ==="
cat > autonomous_drone_cv/mission_controller.py << 'EOF'
# (сюди вставляється повний код місій — я дам його нижче)
EOF

echo "=== Writing trajectory_visualizer.py ==="
cat > autonomous_drone_cv/trajectory_visualizer.py << 'EOF'
# (сюди вставляється код візуалізатора)
EOF

echo "=== Creating README.md ==="
cat > ../../README.md << 'EOF'
# Autonomous Drone System

Повний ROS2 пакет для:
- Pixhawk (PX4)
- RTK GPS
- MAVROS2
- QGroundControl
- OFFBOARD керування
- Місії з YAML
- Візуалізація траєкторії

## Запуск

### 1. MAVROS2 + Pixhawk
ros2 launch mavros px4.launch.py fcu_url:=serial:///dev/ttyACM0:921600

### 2. Місія + траєкторія
ros2 launch autonomous_drone_cv mission.launch.py
EOF

echo "=== Building workspace ==="
cd ../..
colcon build

echo "=== DONE ==="
echo "Repository created in autonomous_drone_system/"
