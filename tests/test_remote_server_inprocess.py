"""
Інтеграція: server.main in-process + GCS monitoring remote.mode=remote.

Сценарій:
  1) POST /api/monitoring/sample при недоступному сервері → offline_queue
  2) Підняти analysis server in-process → flush() → SQLite monitoring_captures
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers_monitoring import write_remote_monitoring_cfg


@pytest.fixture
def monitoring_workspace(tmp_path) -> Dict[str, Path]:
    return {
        "cfg_path": tmp_path / "monitoring.json",
        "queue_dir": tmp_path / "outbox",
        "captures_dir": tmp_path / "caps",
        "findings_file": tmp_path / "findings.json",
    }


@pytest.fixture
def gcs_remote_monitoring(monkeypatch, monitoring_workspace):
    from monitoring import config_loader
    from monitoring.service import reset_monitoring_service

    ws = monitoring_workspace
    write_remote_monitoring_cfg(
        ws["cfg_path"],
        base_url="http://127.0.0.1:1",
        queue_dir=ws["queue_dir"],
        captures_dir=ws["captures_dir"],
        findings_file=ws["findings_file"],
    )
    monkeypatch.setenv("MONITORING_CONFIG", str(ws["cfg_path"]))
    config_loader._CACHE = None
    reset_monitoring_service()
    return ws


def _post_monitoring_sample():
    from web.fleet import get_fleet
    from web.server import app

    app.config["TESTING"] = True
    v = get_fleet().get_vehicle("rover_1")
    ctrl = MagicMock()
    ctrl.get_status.return_value = {
        "connected": True,
        "armed": True,
        "reconnecting": False,
        "gps": {"lat": 50.45, "lon": 30.52},
    }
    with patch.object(v, "get_controller", return_value=ctrl):
        with patch("web.preflight._sim_active", return_value=True):
            with patch("web.geofence.is_enabled", return_value=False):
                with app.test_client() as client:
                    return client.post(
                        "/api/monitoring/sample",
                        data=json.dumps(
                            {"vehicle_id": "rover_1", "crop": "vineyard"}
                        ),
                        content_type="application/json",
                    )


def _sqlite_capture_count(db_path: Path) -> int:
    con = sqlite3.connect(str(db_path))
    try:
        return int(con.execute("SELECT COUNT(*) FROM monitoring_captures").fetchone()[0])
    finally:
        con.close()


def test_remote_sample_offline_queue_then_flush_to_sqlite(
    gcs_remote_monitoring,
    analysis_server,
    monkeypatch,
):
    from monitoring import config_loader
    from monitoring.config_loader import load_monitoring_config
    from monitoring.offline_queue import flush, queue_status

    ws = gcs_remote_monitoring

    r = _post_monitoring_sample()
    assert r.status_code == 200
    assert r.get_json().get("remote_ok") is False
    assert load_monitoring_config()["remote"]["mode"] == "remote"
    assert queue_status()["total_pending"] >= 1

    write_remote_monitoring_cfg(
        ws["cfg_path"],
        base_url=analysis_server["base_url"],
        queue_dir=ws["queue_dir"],
        captures_dir=ws["captures_dir"],
        findings_file=ws["findings_file"],
    )
    config_loader._CACHE = None

    assert flush() >= 1
    assert queue_status()["total_pending"] == 0
    assert _sqlite_capture_count(analysis_server["db_path"]) >= 1


def test_remote_sample_direct_when_server_up(
    monitoring_workspace,
    analysis_server,
    monkeypatch,
):
    from monitoring import config_loader
    from monitoring.service import reset_monitoring_service

    ws = monitoring_workspace
    write_remote_monitoring_cfg(
        ws["cfg_path"],
        base_url=analysis_server["base_url"],
        queue_dir=ws["queue_dir"],
        captures_dir=ws["captures_dir"],
        findings_file=ws["findings_file"],
    )
    monkeypatch.setenv("MONITORING_CONFIG", str(ws["cfg_path"]))
    config_loader._CACHE = None
    reset_monitoring_service()

    r = _post_monitoring_sample()
    assert r.status_code == 200
    assert r.get_json().get("remote_ok") is True
    assert _sqlite_capture_count(analysis_server["db_path"]) >= 1
