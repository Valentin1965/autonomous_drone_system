#!/usr/bin/env bash
# Запуск pytest без ROS 2 entrypoint plugins (launch_testing, lark, …)
set -e
cd "$(dirname "$0")/.."
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export DRONE_SIM_INTERACTIVE=0
exec python -m pytest \
  tests/test_simulator.py \
  tests/test_runtime_config.py \
  tests/test_flask_api.py \
  "$@"
