#!/usr/bin/env bash
# Розробка без заліза: як python main.py --full
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export MAVLINK_PROFILE="${MAVLINK_PROFILE:-sim}"
export DRONE_SIM_INTERACTIVE=0
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
exec python main.py --full "$@"
