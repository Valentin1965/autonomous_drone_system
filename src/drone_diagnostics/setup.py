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
