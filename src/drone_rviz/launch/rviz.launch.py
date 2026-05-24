from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node
import os

def generate_launch_description():
    rviz_config = os.path.join(
        os.path.dirname(__file__), '..', 'rviz', 'mission_view.rviz'
    )

    return LaunchDescription([
        ExecuteProcess(
            cmd=['rviz2', '-d', rviz_config],
            output='screen'
        )
    ])
