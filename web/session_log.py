"""In-memory session event log for field diagnostics."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

_MAX = 400
_lock = threading.Lock()
_events: Deque[Dict[str, Any]] = deque(maxlen=_MAX)


def record(event: str, detail: Optional[str] = None, level: str = "info") -> None:
    with _lock:
        _events.append({
            "ts": time.time(),
            "level": level,
            "event": event,
            "detail": detail or "",
        })


def recent(limit: int = 200) -> List[Dict[str, Any]]:
    with _lock:
        items = list(_events)
    if limit < len(items):
        return items[-limit:]
    return items
