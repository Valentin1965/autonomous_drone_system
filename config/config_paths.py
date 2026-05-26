"""Шляхи до конфігів (варіант 2: SYSTEM_CONFIG / CV_CONFIG)."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def system_config_path() -> Path:
    raw = os.environ.get("SYSTEM_CONFIG", "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else _ROOT / p
    return _ROOT / "config" / "system.yaml"


def cv_config_path() -> str:
    raw = os.environ.get("CV_CONFIG", "").strip()
    if raw:
        p = Path(raw)
        return str(p if p.is_absolute() else _ROOT / p)
    return str(_ROOT / "config" / "cv.yaml")


def project_root() -> Path:
    """Корінь репозиторію (незалежно від cwd при запуску Flask)."""
    return _ROOT
