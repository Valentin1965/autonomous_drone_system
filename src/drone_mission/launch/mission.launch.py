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
