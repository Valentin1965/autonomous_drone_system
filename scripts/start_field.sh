#!/usr/bin/env bash
# Польовий старт (Variant 2, GCS): перевірка analysis server + офлайн-черги + запуск GCS.
set -euo pipefail
cd "$(dirname "$0")/.."

chmod +x scripts/run_variant2_gcs.sh >/dev/null 2>&1 || true

if [[ -d .venv ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

export SYSTEM_CONFIG="${SYSTEM_CONFIG:-config/system_gcs.yaml}"
export MAVLINK_PROFILE="${MAVLINK_PROFILE:-px4}"
export MONITORING_CONFIG="${MONITORING_CONFIG:-config/monitoring.field.yaml}"

echo "Field start — GCS"
echo "  SYSTEM_CONFIG=$SYSTEM_CONFIG"
echo "  MONITORING_CONFIG=$MONITORING_CONFIG"
echo ""

python - <<'PY'
import os, sys, yaml
from pathlib import Path

root = Path(".").resolve()
cfg_path = os.environ.get("MONITORING_CONFIG", "config/monitoring.field.yaml")
path = Path(cfg_path)
if not path.is_absolute():
    path = root / path
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
rcfg = cfg.get("remote") or {}
qcfg = cfg.get("offline_queue") or {}

base = (rcfg.get("base_url") or "").rstrip("/")
health = rcfg.get("health_path") or "/health"
queue_dir = qcfg.get("queue_dir") or "data/monitoring/outbox"

print(f"[check] analysis base_url: {base or '—'}")
print(f"[check] health_path     : {health}")
print(f"[check] offline queue   : {queue_dir}")
PY

echo ""
echo "[check] offline queue files:"
python - <<'PY'
import os, yaml
from pathlib import Path

root = Path(".").resolve()
cfg_path = os.environ.get("MONITORING_CONFIG", "config/monitoring.field.yaml")
path = Path(cfg_path)
if not path.is_absolute():
    path = root / path
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
qdir = (cfg.get("offline_queue") or {}).get("queue_dir") or "data/monitoring/outbox"
qpath = Path(qdir)
if not qpath.is_absolute():
    qpath = root / qpath
qpath.mkdir(parents=True, exist_ok=True)
items = list(qpath.glob("*"))
events = len([p for p in items if p.name.endswith("_event.json")])
caps = len([p for p in items if p.name.endswith("_capture.json")])
print(f"  pending_total={len(items)}  events={events}  captures={caps}")
if len(items) > 0:
    print("  WARN: є невідправлені елементи черги (після старту натисніть Queue → Flush у GCS або POST /api/monitoring/queue/flush)")
PY

echo ""
echo "[check] analysis server health (якщо запущено):"
python - <<'PY'
import os, yaml, json, urllib.request
from pathlib import Path

root = Path(".").resolve()
cfg_path = os.environ.get("MONITORING_CONFIG", "config/monitoring.field.yaml")
path = Path(cfg_path)
if not path.is_absolute():
    path = root / path
cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
rcfg = cfg.get("remote") or {}
base = (rcfg.get("base_url") or "").rstrip("/")
health = rcfg.get("health_path") or "/health"
key = (rcfg.get("api_key") or "").strip()

if not base:
    print("  SKIP: remote.base_url порожній")
    raise SystemExit(0)

url = base + health
req = urllib.request.Request(url, headers={"Accept": "application/json"})
if key:
    req.add_header("Authorization", "Bearer " + key)
try:
    with urllib.request.urlopen(req, timeout=2.5) as r:
        data = r.read().decode("utf-8", "ignore")
        print("  OK:", url)
        print("  ", data[:200].replace("\\n"," "))
except Exception as e:
    print("  WARN: analysis server не відповідає:", url)
    print("  ", e)
PY

echo ""
echo "Starting GCS…  http://127.0.0.1:8080/"
exec python main.py --web "$@"

