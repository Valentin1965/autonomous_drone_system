#!/usr/bin/env bash
# Варіант 2 — станція керування (GCS → Pixhawk по телеметрії)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -d .venv ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

export SYSTEM_CONFIG="${SYSTEM_CONFIG:-config/system_gcs.yaml}"
export MAVLINK_PROFILE=px4
export MONITORING_CONFIG="${MONITORING_CONFIG:-config/monitoring.field.yaml}"

echo "Variant 2 — Ground Station (GCS)"
echo "  SYSTEM_CONFIG=$SYSTEM_CONFIG"
echo "  MONITORING_CONFIG=$MONITORING_CONFIG"
echo "  Відредагуйте connection_px4 у system_gcs.yaml (IP телеметрії)"
echo "  Браузер: http://127.0.0.1:8080/"
echo ""

exec python main.py --web "$@"
