import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/enovo_my/autonomous_drone_system/install/drone_visualizer'
