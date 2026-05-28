#!/usr/bin/env bash
# Запуск pytest без ROS 2 entrypoint plugins (launch_testing → lark, …)
# Якщо в терміналі: source /opt/ros/humble/setup.bash — звичайний pytest може падати.
set -e
cd "$(dirname "$0")/.."
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export DRONE_SIM_INTERACTIVE=0
exec python -m pytest tests/ -q -m "not slow" "$@"
