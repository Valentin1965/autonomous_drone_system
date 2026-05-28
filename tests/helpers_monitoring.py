"""Спільні хелпери для тестів monitoring + analysis server."""

from __future__ import annotations

import json
import socket
from pathlib import Path


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def write_remote_monitoring_cfg(
    path: Path,
    *,
    base_url: str,
    queue_dir: Path,
    captures_dir: Path,
    findings_file: Path,
    demo_findings_in_sim: bool = False,
) -> None:
    cfg = {
        "enabled": True,
        "default_crop": "vineyard",
        "station": {"id": "gcs-test", "operator": "pytest"},
        "uplink": {"source": "local"},
        "remote": {
            "enabled": True,
            "mode": "remote",
            "base_url": base_url,
            "analyze_path": "/api/v1/analyze",
            "health_path": "/health",
            "timeout_s": 8,
            "api_key": "",
            "sync_events": False,
            "save_captures": True,
            "captures_dir": str(captures_dir),
        },
        "offline_queue": {
            "enabled": True,
            "queue_dir": str(queue_dir),
            "retry_interval_s": 999,
            "max_retries": 0,
            "max_queue_size": 500,
            "flush_delay_s": 0.0,
        },
        "cameras": {
            "left": {"type": "synthetic", "source": "0", "label": "L"},
            "right": {"type": "synthetic", "source": "1", "label": "R"},
        },
        "crops": {"vineyard": {"name": "Виноград", "issue_labels": ["downy_mildew"]}},
        "survey": {
            "dwell_s": 0.2,
            "min_confidence": 0.4,
            "speed_m_s": 0.6,
            "use_cv_frame": False,
        },
        "demo_findings_in_sim": demo_findings_in_sim,
        "storage": {"findings_file": str(findings_file)},
    }
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
