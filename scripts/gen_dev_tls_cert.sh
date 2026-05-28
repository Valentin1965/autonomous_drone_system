#!/usr/bin/env bash
# Self-signed TLS для dev GCS (web.tls у config/system.yaml)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=config/certs
mkdir -p "$OUT"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$OUT/dev-gcs.key" \
  -out "$OUT/dev-gcs.crt" \
  -days 825 \
  -subj "/CN=ground-rover-gcs-dev"
echo "Created $OUT/dev-gcs.crt and dev-gcs.key"
echo "Set web.tls.enabled: true in config/system.yaml (or system_gcs.yaml)"
