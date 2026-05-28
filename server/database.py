"""
SQLite сховище сервера аналізу.

Одна інстанція бази обслуговує ВСІ станції (багато GCS → один сервер).
Таблиця fleet_events зберігає: де, коли, що робили, що вносили (оприскування),
який результат, хто оператор, знімки моніторингу, висновки YOLO.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_db_path: Optional[Path] = None


def init_db(path: Path) -> None:
    """Ініціалізація бази. Викликати один раз при старті сервера."""
    global _db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    _db_path = path
    with _connect() as conn:
        conn.executescript(
            """
            -- Журнал роботи флоту: маршрути, оприскування, обстеження, оператор
            CREATE TABLE IF NOT EXISTS fleet_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL    NOT NULL,
                station_id   TEXT    NOT NULL DEFAULT '',
                operator     TEXT    NOT NULL DEFAULT '',
                vehicle_id   TEXT    NOT NULL DEFAULT '',
                event_type   TEXT    NOT NULL,
                lat          REAL,
                lon          REAL,
                detail       TEXT    NOT NULL DEFAULT '',
                payload_json TEXT    NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_fe_ts      ON fleet_events(ts);
            CREATE INDEX IF NOT EXISTS idx_fe_vehicle ON fleet_events(vehicle_id);
            CREATE INDEX IF NOT EXISTS idx_fe_station ON fleet_events(station_id);
            CREATE INDEX IF NOT EXISTS idx_fe_type    ON fleet_events(event_type);

            -- Знімки моніторингу (2 камери з дрона / RPi)
            CREATE TABLE IF NOT EXISTS monitoring_captures (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_id       TEXT    UNIQUE NOT NULL,
                ts               REAL    NOT NULL,
                station_id       TEXT    NOT NULL DEFAULT '',
                operator         TEXT    NOT NULL DEFAULT '',
                vehicle_id       TEXT    NOT NULL DEFAULT '',
                crop             TEXT    NOT NULL DEFAULT '',
                lat              REAL,
                lon              REAL,
                source           TEXT    NOT NULL DEFAULT 'survey',
                left_image_path  TEXT    NOT NULL DEFAULT '',
                right_image_path TEXT    NOT NULL DEFAULT '',
                context_json     TEXT    NOT NULL DEFAULT '{}',
                analysis_message TEXT    NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_mc_vehicle  ON monitoring_captures(vehicle_id);
            CREATE INDEX IF NOT EXISTS idx_mc_station  ON monitoring_captures(station_id);
            CREATE INDEX IF NOT EXISTS idx_mc_ts       ON monitoring_captures(ts);

            -- Висновки YOLO по кожному знімку
            CREATE TABLE IF NOT EXISTS monitoring_detections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_id TEXT    NOT NULL,
                camera     TEXT    NOT NULL DEFAULT '',
                label      TEXT    NOT NULL DEFAULT '',
                confidence REAL    NOT NULL DEFAULT 0,
                issue_type TEXT    NOT NULL DEFAULT '',
                severity   TEXT    NOT NULL DEFAULT '',
                FOREIGN KEY (capture_id) REFERENCES monitoring_captures(capture_id)
            );
            CREATE INDEX IF NOT EXISTS idx_md_capture ON monitoring_detections(capture_id);
            CREATE INDEX IF NOT EXISTS idx_md_label   ON monitoring_detections(label);
            """
        )
        conn.commit()


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Fleet events ──────────────────────────────────────────────────────────

def insert_fleet_event(
    *,
    event_type: str,
    station_id: str = "",
    operator: str = "",
    vehicle_id: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    detail: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> int:
    with _lock:
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO fleet_events
                (ts, station_id, operator, vehicle_id, event_type, lat, lon, detail, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    station_id,
                    operator,
                    vehicle_id,
                    event_type,
                    lat,
                    lon,
                    detail,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)


# ─── Captures ──────────────────────────────────────────────────────────────

def insert_capture(
    *,
    capture_id: str,
    station_id: str,
    operator: str,
    vehicle_id: str,
    crop: str,
    lat: float,
    lon: float,
    source: str,
    left_image_path: str,
    right_image_path: str,
    context: Optional[Dict[str, Any]],
    analysis_message: str = "",
) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO monitoring_captures
                (capture_id, ts, station_id, operator, vehicle_id, crop, lat, lon, source,
                 left_image_path, right_image_path, context_json, analysis_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    time.time(),
                    station_id,
                    operator,
                    vehicle_id,
                    crop,
                    lat,
                    lon,
                    source,
                    left_image_path,
                    right_image_path,
                    json.dumps(context or {}, ensure_ascii=False),
                    analysis_message,
                ),
            )
            conn.commit()


def insert_detections(capture_id: str, detections: List[Dict[str, Any]]) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM monitoring_detections WHERE capture_id = ?",
                (capture_id,),
            )
            conn.executemany(
                """
                INSERT INTO monitoring_detections
                (capture_id, camera, label, confidence, issue_type, severity)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        capture_id,
                        d.get("camera", ""),
                        d.get("label", ""),
                        float(d.get("confidence", 0)),
                        d.get("issue_type", ""),
                        d.get("severity", ""),
                    )
                    for d in detections
                ],
            )
            conn.commit()


# ─── Queries ───────────────────────────────────────────────────────────────

def list_findings(
    *,
    station_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    crop: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    q = """
        SELECT d.capture_id, d.camera AS camera_side, d.label, d.confidence,
               d.issue_type, d.severity,
               c.crop, c.vehicle_id, c.station_id, c.operator,
               c.lat, c.lon, c.ts, c.source
        FROM monitoring_detections d
        JOIN monitoring_captures c ON c.capture_id = d.capture_id
        WHERE 1=1
    """
    params: List[Any] = []
    if station_id:
        q += " AND c.station_id = ?"
        params.append(station_id)
    if vehicle_id:
        q += " AND c.vehicle_id = ?"
        params.append(vehicle_id)
    if crop:
        q += " AND c.crop = ?"
        params.append(crop)
    q += " ORDER BY c.ts DESC LIMIT ?"
    params.append(int(limit))

    with _lock:
        rows = _connect().execute(q, params).fetchall()

    return [
        {
            "capture_id": r["capture_id"],
            "camera_side": r["camera_side"] or "",
            "label": r["label"],
            "confidence": float(r["confidence"]),
            "issue_type": r["issue_type"],
            "severity": r["severity"],
            "crop": r["crop"],
            "vehicle_id": r["vehicle_id"],
            "station_id": r["station_id"] or "",
            "operator": r["operator"] or "",
            "lat": float(r["lat"] or 0),
            "lon": float(r["lon"] or 0),
            "source": r["source"],
            "created_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(float(r["ts"]))
            ),
        }
        for r in rows
    ]


def list_operations(
    *,
    station_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    q = "SELECT * FROM fleet_events WHERE 1=1"
    params: List[Any] = []
    if station_id:
        q += " AND station_id = ?"
        params.append(station_id)
    if vehicle_id:
        q += " AND vehicle_id = ?"
        params.append(vehicle_id)
    if event_type:
        q += " AND event_type = ?"
        params.append(event_type)
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(int(limit))

    with _lock:
        rows = _connect().execute(q, params).fetchall()

    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        out.append(
            {
                "id": r["id"],
                "ts": r["ts"],
                "time": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.localtime(float(r["ts"]))
                ),
                "station_id": r["station_id"],
                "operator": r["operator"],
                "vehicle_id": r["vehicle_id"],
                "event_type": r["event_type"],
                "lat": r["lat"],
                "lon": r["lon"],
                "detail": r["detail"],
                "payload": payload,
            }
        )
    return out


def stats() -> Dict[str, Any]:
    with _lock:
        conn = _connect()
        fleet_events = conn.execute("SELECT COUNT(*) FROM fleet_events").fetchone()[0]
        captures = conn.execute("SELECT COUNT(*) FROM monitoring_captures").fetchone()[0]
        detections = conn.execute(
            "SELECT COUNT(*) FROM monitoring_detections"
        ).fetchone()[0]
        stations = conn.execute(
            "SELECT COUNT(DISTINCT station_id) FROM fleet_events"
        ).fetchone()[0]
    return {
        "fleet_events": fleet_events,
        "monitoring_captures": captures,
        "monitoring_detections": detections,
        "stations_seen": stations,
    }
