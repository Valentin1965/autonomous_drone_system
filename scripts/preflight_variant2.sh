#!/usr/bin/env bash
# Перевірка борту (варіант 2) перед виїздом на RPi.
# Запуск: bash scripts/preflight_variant2.sh
# На GCS-ноутбуці без RPi — пропустіть depthai/serial.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "  ✓ $1"; }
warn() { echo "  ⚠ $1"; }
bad() { echo "  ✗ $1"; FAIL=1; }

echo "=== Preflight variant 2 — $(date) ==="
echo "ROOT=$ROOT"

echo ""
echo "[Python]"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  bad "python3 не знайдено"
  PY=
fi
if [[ -n "${PY:-}" ]]; then
  ok "$($PY --version 2>&1)"
  $PY -c "import flask, pymavlink, cv2, yaml" 2>/dev/null && ok "flask, pymavlink, cv2, yaml" || bad "відсутні Python-пакети (pip install -r requirements.txt)"
  $PY -c "from ultralytics import YOLO" 2>/dev/null && ok "ultralytics/YOLO" || warn "ultralytics не встановлено (потрібно для CV)"
fi

echo ""
echo "[Конфіги]"
for f in config/system_rpi.yaml config/cv_rpi.yaml; do
  [[ -f "$f" ]] && ok "$f" || warn "$f відсутній"
done

echo ""
echo "[Диск]"
AVAIL=$(df -k "$ROOT" 2>/dev/null | awk 'NR==2 {print $4}')
if [[ -n "${AVAIL:-}" ]] && [[ "$AVAIL" -lt 500000 ]]; then
  warn "мало вільного місця (<500 MB): ${AVAIL} KB"
else
  ok "вільне місце на диску OK"
fi

echo ""
echo "[MAVLink serial — RPi]"
DEV="${MAVLINK_DEVICE:-/dev/ttyACM0}"
if [[ -e "$DEV" ]]; then
  ok "пристрій $DEV існує"
  groups 2>/dev/null | grep -q dialout && ok "користувач у групі dialout" || warn "додайте користувача в dialout: sudo usermod -aG dialout \$USER"
else
  warn "$DEV не знайдено (нормально на ноутбуці GCS)"
fi

echo ""
echo "[Oak-D / depthai — RPi]"
if [[ -n "${PY:-}" ]]; then
  $PY -c "import depthai" 2>/dev/null && ok "depthai" || warn "depthai не встановлено (pip install depthai)"
fi

echo ""
echo "[YOLO модель]"
MODEL_DIR="${ROOT}/models"
if compgen -G "${MODEL_DIR}/*.pt" >/dev/null 2>&1; then
  ok "модель у models/"
else
  warn "немає *.pt у models/ (завантажиться yolov8s-seg.pt)"
fi

echo ""
if [[ "$FAIL" -eq 0 ]]; then
  echo "=== Preflight: OK (перевірте попередження) ==="
  exit 0
else
  echo "=== Preflight: FAILED ==="
  exit 1
fi
