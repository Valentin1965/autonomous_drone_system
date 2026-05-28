"""
Точка входу аналітичного сервера.

Запуск:
    python -m server.main [--port 8090] [--vineyard-weights model.pt]
  або через скрипт:
    python scripts/start_analysis_server.py --port 8090

Один сервер обслуговує БАГАТО станцій (GCS).
Не залежить від web/, monitoring/, simulator/.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server import config as cfg
from server import database as db
from server import yolo_engine as yolo
from server.app import app


def main() -> None:
    p = argparse.ArgumentParser(description="Fleet analysis server (YOLO + SQLite)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--device", default="")
    p.add_argument("--confidence", type=float, default=0.0)
    p.add_argument("--api-key", default="")
    p.add_argument("--db", default="", help="SQLite path (overrides config/server.yaml)")
    p.add_argument("--default-weights", default="")
    p.add_argument("--vineyard-weights", default="")
    p.add_argument("--banana-weights", default="")
    args = p.parse_args()

    # Аргументи командного рядка перебивають config/server.yaml і env
    if args.api_key:
        os.environ["MONITORING_API_KEY"] = args.api_key
    if args.device:
        os.environ["YOLO_DEVICE"] = args.device
    if args.confidence:
        os.environ["YOLO_CONF"] = str(args.confidence)
    if args.default_weights:
        os.environ["MONITORING_DEFAULT_WEIGHTS"] = args.default_weights
    if args.vineyard_weights:
        os.environ["MONITORING_VINEYARD_WEIGHTS"] = args.vineyard_weights
    if args.banana_weights:
        os.environ["MONITORING_BANANA_WEIGHTS"] = args.banana_weights

    # config перечитується після env
    import server.config as _cfg_mod
    _cfg_mod._CACHE = None

    db_p = Path(args.db) if args.db else cfg.db_path()
    db.init_db(db_p)
    cfg.captures_dir().mkdir(parents=True, exist_ok=True)

    weights = cfg.model_weights()
    device = cfg.yolo_device()
    confidence = cfg.yolo_confidence()
    yolo.setup(device, confidence, weights)

    print(f"\n{'='*55}")
    print(f"  Fleet analysis server — http://{args.host}:{args.port}")
    print(f"  DB   : {db_p}")
    print(f"  YOLO : device={device}  conf={confidence}")
    print(f"  Models loaded : {yolo.models_loaded() or '— (none, captures only)'}")
    if cfg.api_key():
        print("  Auth : Authorization: Bearer <api_key>")
    print("  GET  /  /dashboard  /health  /api/v1/stats")
    print("  POST /api/v1/analyze  /api/v1/events")
    print("  GET  /api/v1/findings  /api/v1/operations  /api/v1/spray/coverage")
    print(f"{'='*55}\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
