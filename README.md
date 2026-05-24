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
