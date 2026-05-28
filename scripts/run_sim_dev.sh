#!/usr/bin/env bash
# Розробка без заліза: симулятор + GCS + analysis server (remote.mode: remote)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export MAVLINK_PROFILE="${MAVLINK_PROFILE:-sim}"
export DRONE_SIM_INTERACTIVE=0
export MONITORING_CONFIG="${MONITORING_CONFIG:-config/monitoring.dev.yaml}"
ANALYSIS_PORT="${ANALYSIS_PORT:-8090}"
ANALYSIS_PID=""

cleanup() {
  if [[ -n "${ANALYSIS_PID}" ]] && kill -0 "${ANALYSIS_PID}" 2>/dev/null; then
    kill "${ANALYSIS_PID}" 2>/dev/null || true
    wait "${ANALYSIS_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "Starting analysis server on http://127.0.0.1:${ANALYSIS_PORT} (remote.mode: remote)..."
python -m server.main --host 127.0.0.1 --port "${ANALYSIS_PORT}" &
ANALYSIS_PID=$!

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${ANALYSIS_PORT}/health" >/dev/null 2>&1; then
    echo "Analysis server ready (dashboard: http://127.0.0.1:${ANALYSIS_PORT}/dashboard)."
    break
  fi
  sleep 0.25
done

exec python main.py --full "$@"
