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
