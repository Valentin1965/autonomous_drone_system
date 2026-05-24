from setuptools import setup

package_name = 'drone_rviz'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/rviz', ['rviz/mission_view.rviz']),
        ('share/' + package_name + '/launch', ['launch/rviz.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Valentyn',
    maintainer_email='land.market0@gmail.com',
    description='RViz2 visualization for autonomous drone system',
    entry_points={
        'console_scripts': [],
    },
)
