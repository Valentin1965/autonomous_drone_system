#!/usr/bin/env python3
"""
Надіслати один JPEG з RPi на станцію (uplink.source: rpi).

Приклад:
  python scripts/rpi_monitoring_upload.py \\
    --gcs http://192.168.1.50:8080 \\
    --vehicle rover_1 --side left --image /tmp/left.jpg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="RPi → GCS monitoring upload")
    p.add_argument("--gcs", required=True, help="Base URL станції, напр. http://192.168.1.50:8080")
    p.add_argument("--vehicle", default="rover_1")
    p.add_argument("--side", choices=("left", "right"), required=True)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--token", default="", help="X-Upload-Token якщо задано в monitoring.yaml")
    args = p.parse_args()

    try:
        import requests
    except ImportError:
        print("pip install requests", file=sys.stderr)
        return 1

    url = args.gcs.rstrip("/") + "/api/monitoring/upload"
    headers = {}
    if args.token:
        headers["X-Upload-Token"] = args.token

    with open(args.image, "rb") as f:
        r = requests.post(
            url,
            headers=headers,
            data={"vehicle_id": args.vehicle, "side": args.side},
            files={"image": (args.image.name, f, "image/jpeg")},
            timeout=30,
        )
    print(r.status_code, r.text[:500])
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
