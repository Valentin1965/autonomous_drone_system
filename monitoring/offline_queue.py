"""
Черга офлайн-відправки на станції.

Якщо зв'язок з сервером (5G/Wi-Fi) відсутній — запити зберігаються
на диск станції та автоматично досилаються при відновленні мережі.

Структура черги (папка outbox/):
    <ts>_<uuid>_event.json       — подія (JSON-тіло для /api/v1/events)
    <ts>_<uuid>_capture.json     — метадані знімка
    <ts>_<uuid>_capture_left.jpg — лівий JPEG
    <ts>_<uuid>_capture_right.jpg— правий JPEG

Retry-воркер — окремий daemon-потік, один на процес станції.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from monitoring.config_loader import load_monitoring_config

_worker_started = False
_worker_lock = threading.Lock()


# ─── Конфіг черги ─────────────────────────────────────────────────────────

def _qcfg() -> Dict[str, Any]:
    return load_monitoring_config().get("offline_queue") or {}


def _queue_enabled() -> bool:
    return bool(_qcfg().get("enabled", True))


def _queue_dir() -> Path:
    from monitoring.config_loader import _root

    rel = _qcfg().get("queue_dir", "data/monitoring/outbox")
    p = Path(rel)
    d = p if p.is_absolute() else _root() / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def _retry_interval() -> float:
    try:
        return float(_qcfg().get("retry_interval_s", 30))
    except (TypeError, ValueError):
        return 30.0


def _max_retries() -> int:
    try:
        return int(_qcfg().get("max_retries", 0))
    except (TypeError, ValueError):
        return 0


def _max_queue_size() -> int:
    try:
        return int(_qcfg().get("max_queue_size", 500))
    except (TypeError, ValueError):
        return 500


def _flush_delay() -> float:
    try:
        return float(_qcfg().get("flush_delay_s", 0.5))
    except (TypeError, ValueError):
        return 0.5


# ─── Запис у чергу ────────────────────────────────────────────────────────

def _item_id() -> str:
    return f"{int(time.time()*1000)}_{str(uuid.uuid4())[:8]}"


def enqueue_event(body: Dict[str, Any]) -> Optional[str]:
    """Зберегти подію флоту у чергу. Повертає item_id або None якщо черга вимкнена."""
    if not _queue_enabled():
        return None
    qdir = _queue_dir()
    _trim_if_needed(qdir)
    item_id = _item_id()
    path = qdir / f"{item_id}_event.json"
    data = {
        "type": "event",
        "item_id": item_id,
        "retries": 0,
        "created_at": time.time(),
        "body": body,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return item_id


def enqueue_capture(
    meta: Dict[str, Any],
    left_jpeg: Optional[bytes],
    right_jpeg: Optional[bytes],
) -> Optional[str]:
    """Зберегти знімок моніторингу у чергу."""
    if not _queue_enabled():
        return None
    qdir = _queue_dir()
    _trim_if_needed(qdir)
    item_id = _item_id()

    left_path = right_path = ""
    if left_jpeg:
        p = qdir / f"{item_id}_capture_left.jpg"
        p.write_bytes(left_jpeg)
        left_path = p.name
    if right_jpeg:
        p = qdir / f"{item_id}_capture_right.jpg"
        p.write_bytes(right_jpeg)
        right_path = p.name

    data = {
        "type": "capture",
        "item_id": item_id,
        "retries": 0,
        "created_at": time.time(),
        "meta": meta,
        "left_file": left_path,
        "right_file": right_path,
    }
    path = qdir / f"{item_id}_capture.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return item_id


# ─── Відправка одного елемента ────────────────────────────────────────────

def _send_event(item: Dict[str, Any]) -> bool:
    """POST /api/v1/events на сервер. True = успішно."""
    import requests

    from monitoring.config_loader import load_monitoring_config

    rcfg = load_monitoring_config().get("remote") or {}
    base = (rcfg.get("base_url") or "").rstrip("/")
    url = f"{base}/api/v1/events"
    headers = {"Content-Type": "application/json"}
    key = (rcfg.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = requests.post(
            url,
            data=json.dumps(item["body"], ensure_ascii=False),
            headers=headers,
            timeout=15,
        )
        return r.status_code < 500
    except Exception:
        return False


def _send_capture(item: Dict[str, Any], qdir: Path) -> bool:
    """POST /api/v1/analyze multipart. True = успішно."""
    import requests

    from monitoring.config_loader import load_monitoring_config

    rcfg = load_monitoring_config().get("remote") or {}
    base = (rcfg.get("base_url") or "").rstrip("/")
    path = rcfg.get("analyze_path") or "/api/v1/analyze"
    url = f"{base}{path}"
    headers: Dict[str, str] = {}
    key = (rcfg.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    meta = item.get("meta") or {}
    files: Dict[str, Any] = {}
    left_file = qdir / item.get("left_file", "")
    right_file = qdir / item.get("right_file", "")
    if item.get("left_file") and left_file.is_file():
        files["left_image"] = ("left.jpg", left_file.read_bytes(), "image/jpeg")
    if item.get("right_file") and right_file.is_file():
        files["right_image"] = ("right.jpg", right_file.read_bytes(), "image/jpeg")
    if not files:
        return True  # нічого слати, вважаємо виконаним

    data = {k: str(v) for k, v in meta.items() if k != "context"}
    if "context" in meta:
        data["context_json"] = json.dumps(meta["context"], ensure_ascii=False)
    try:
        r = requests.post(url, data=data, files=files, headers=headers, timeout=60)
        return r.status_code < 500
    except Exception:
        return False


# ─── Flush — спробувати відправити всі елементи черги ─────────────────────

def flush() -> int:
    """
    Спробувати відправити всі елементи черги.
    Повертає кількість успішно відправлених.
    """
    qdir = _queue_dir()
    sent = 0
    max_r = _max_retries()
    delay = _flush_delay()

    # Знаходимо всі JSON-файли черги
    candidates: List[Path] = sorted(
        [p for p in qdir.iterdir() if p.suffix == ".json"],
        key=lambda p: p.stat().st_mtime,
    )

    for json_path in candidates:
        try:
            item = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            json_path.unlink(missing_ok=True)
            continue

        item_type = item.get("type")
        ok = False

        if item_type == "event":
            ok = _send_event(item)
        elif item_type == "capture":
            ok = _send_capture(item, qdir)

        if ok:
            # Видалити JSON і супутні JPEG
            _remove_item(json_path, item, qdir)
            sent += 1
        else:
            item["retries"] = item.get("retries", 0) + 1
            if max_r > 0 and item["retries"] >= max_r:
                # Перемістити в архів помилок (не видаляти — для діагностики)
                failed_dir = qdir / "failed"
                failed_dir.mkdir(exist_ok=True)
                json_path.replace(failed_dir / json_path.name)
                _move_jpeg_to_failed(item, qdir, failed_dir)
            else:
                json_path.write_text(
                    json.dumps(item, ensure_ascii=False), encoding="utf-8"
                )

        if delay > 0 and ok:
            time.sleep(delay)

    return sent


def _remove_item(json_path: Path, item: Dict[str, Any], qdir: Path) -> None:
    json_path.unlink(missing_ok=True)
    for key in ("left_file", "right_file"):
        fname = item.get(key)
        if fname:
            (qdir / fname).unlink(missing_ok=True)


def _move_jpeg_to_failed(
    item: Dict[str, Any], qdir: Path, failed_dir: Path
) -> None:
    for key in ("left_file", "right_file"):
        fname = item.get(key)
        if fname and (qdir / fname).is_file():
            (qdir / fname).replace(failed_dir / fname)


# ─── Trim ─────────────────────────────────────────────────────────────────

def _trim_if_needed(qdir: Path) -> None:
    max_size = _max_queue_size()
    items = sorted(
        [p for p in qdir.iterdir() if p.suffix == ".json"],
        key=lambda p: p.stat().st_mtime,
    )
    while len(items) > max_size:
        oldest = items.pop(0)
        try:
            item = json.loads(oldest.read_text(encoding="utf-8"))
            _remove_item(oldest, item, qdir)
        except Exception:
            oldest.unlink(missing_ok=True)


# ─── Статус черги ─────────────────────────────────────────────────────────

def queue_size() -> int:
    try:
        return sum(1 for p in _queue_dir().iterdir() if p.suffix == ".json")
    except Exception:
        return 0


def queue_status() -> Dict[str, Any]:
    qdir = _queue_dir()
    events = captures = failed = 0
    try:
        for p in qdir.iterdir():
            if p.suffix != ".json":
                continue
            try:
                t = json.loads(p.read_text(encoding="utf-8")).get("type", "")
                if t == "event":
                    events += 1
                elif t == "capture":
                    captures += 1
            except Exception:
                pass
        failed_dir = qdir / "failed"
        if failed_dir.is_dir():
            failed = sum(1 for p in failed_dir.iterdir() if p.suffix == ".json")
    except Exception:
        pass
    return {
        "enabled": _queue_enabled(),
        "queue_dir": str(qdir),
        "pending_events": events,
        "pending_captures": captures,
        "failed": failed,
        "total_pending": events + captures,
    }


# ─── Retry worker ─────────────────────────────────────────────────────────

def _worker_loop() -> None:
    """Daemon-потік: кожні retry_interval_s пробує flush()."""
    while True:
        interval = _retry_interval()
        time.sleep(interval)
        if not _queue_enabled():
            continue
        # Перевіряємо, чи є щось у черзі
        if queue_size() == 0:
            continue
        # Перевіряємо, чи сервер доступний (легкий GET /health)
        if not _server_reachable():
            continue
        try:
            n = flush()
            if n:
                print(f"[OfflineQueue] flushed {n} item(s) to server")
        except Exception as e:
            print(f"[OfflineQueue] flush error: {e}")


def _server_reachable() -> bool:
    import requests

    from monitoring.config_loader import load_monitoring_config

    rcfg = load_monitoring_config().get("remote") or {}
    base = (rcfg.get("base_url") or "").rstrip("/")
    health_path = rcfg.get("health_path") or "/health"
    try:
        r = requests.get(f"{base}{health_path}", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def ensure_worker_started() -> None:
    """Запустити retry-воркер один раз при старті станції."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        if not _queue_enabled():
            return
        t = threading.Thread(
            target=_worker_loop,
            name="offline-queue-worker",
            daemon=True,
        )
        t.start()
        _worker_started = True
        print(
            f"[OfflineQueue] worker started — retry every {_retry_interval():.0f}s, "
            f"queue: {_queue_dir()}"
        )
