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
