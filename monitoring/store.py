"""Збереження знахідок моніторингу (JSON)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from monitoring.config_loader import findings_path
from monitoring.models import normalize_finding

_lock = threading.Lock()


def _ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("[]", encoding="utf-8")


def load_findings() -> List[Dict[str, Any]]:
    path = findings_path()
    with _lock:
        _ensure_file(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = []
    if not isinstance(data, list):
        return []
    return [normalize_finding(x) for x in data if isinstance(x, dict)]


def save_findings(items: List[Dict[str, Any]]) -> None:
    path = findings_path()
    with _lock:
        _ensure_file(path)
        normalized = [normalize_finding(x) for x in items]
        path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def append_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    items = load_findings()
    rec = normalize_finding(finding)
    items.append(rec)
    save_findings(items)
    return rec


def clear_findings(
    *,
    vehicle_id: Optional[str] = None,
    crop: Optional[str] = None,
) -> int:
    items = load_findings()
    before = len(items)

    def _keep(f: Dict[str, Any]) -> bool:
        if vehicle_id and f.get("vehicle_id") == vehicle_id:
            return False
        if crop and f.get("crop") == crop:
            return False
        if vehicle_id or crop:
            return True
        return False

    if vehicle_id or crop:
        items = [f for f in items if _keep(f)]
    else:
        items = []
    save_findings(items)
    return before - len(items)


def query_findings(
    *,
    vehicle_id: Optional[str] = None,
    crop: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    items = load_findings()
    if vehicle_id:
        items = [f for f in items if f.get("vehicle_id") == vehicle_id]
    if crop:
        items = [f for f in items if f.get("crop") == crop]
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items[: max(1, int(limit))]
