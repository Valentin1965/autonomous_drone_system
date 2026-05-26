#!/usr/bin/env bash
# Варіант 2 — борт: RPi + Pixhawk (CV + MAVLink serial)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [[ -d .venv ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

export SYSTEM_CONFIG="${SYSTEM_CONFIG:-config/system_rpi.yaml}"
export CV_CONFIG="${CV_CONFIG:-config/cv_rpi.yaml}"
export MAVLINK_PROFILE=px4
export CV_SOURCE="${CV_SOURCE:-oakd}"

echo "Variant 2 — RPi companion"
echo "  SYSTEM_CONFIG=$SYSTEM_CONFIG"
echo "  CV_CONFIG=$CV_CONFIG"
echo "  MAVLink → Pixhawk (serial у system_rpi.yaml)"
echo ""
echo "Переконайтесь: Pixhawk підключено USB, права dialout:"
echo "  sudo usermod -aG dialout \$USER"
echo ""

exec python main.py --cv "$@"
