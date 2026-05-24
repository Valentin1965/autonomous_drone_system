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
