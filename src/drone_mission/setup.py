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
