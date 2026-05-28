#!/usr/bin/env python3
"""
Ярлик запуску аналітичного сервера.

Приклади:
  python scripts/start_analysis_server.py
  python scripts/start_analysis_server.py --port 8090 --vineyard-weights /path/to/model.pt
  python scripts/start_analysis_server.py --device cuda --confidence 0.5
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.main import main

if __name__ == "__main__":
    main()
