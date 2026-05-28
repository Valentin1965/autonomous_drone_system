"""Обстеження: зупинка на точці → 2 камери → віддалений YOLO."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from monitoring.analyzer import analyze_point
from monitoring.config_loader import load_monitoring_config
from monitoring.models import new_finding
from monitoring.store import append_finding

if TYPE_CHECKING:
    from web.vehicle import Vehicle


def _gps_valid(gps: Optional[dict]) -> bool:
    if not gps:
        return False
    try:
        lat, lon = float(gps["lat"]), float(gps["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    return abs(lat) > 1e-4 or abs(lon) > 1e-4


def _current_gps(vehicle: "Vehicle") -> dict:
    from simulator import fleet_registry

    sim = fleet_registry.get_position(vehicle.id)
    if sim:
        return dict(sim)
    return dict(vehicle.get_controller().get_status().get("gps") or {})


class SurveyRunner:
    def __init__(self, vehicle: "Vehicle", crop_id: str):
        self.vehicle = vehicle
        self.crop_id = crop_id
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.phase = "idle"
        self.index = 0
        self.total = 0
        self._findings_count = 0
        self._last_message = ""

    @property
    def active(self) -> bool:
        with self._lock:
            return self.phase == "running"

    def status(self) -> dict:
        with self._lock:
            return {
                "active": self.phase == "running",
                "phase": self.phase,
                "index": self.index,
                "total": self.total,
                "findings_count": self._findings_count,
                "crop": self.crop_id,
                "vehicle_id": self.vehicle.id,
                "message": self._last_message,
            }

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        with self._lock:
            if self.phase == "running":
                self.phase = "stopped"
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None

    def start(self, waypoints: List[Dict[str, float]]) -> dict:
        if not waypoints:
            raise ValueError("empty survey route")
        if self.vehicle.control_mode != "autonomous":
            raise ValueError("Увімкніть автономний режим для обстеження")

        self.stop(wait=True)
        self._stop.clear()
        with self._lock:
            self.phase = "running"
            self.index = 0
            self.total = len(waypoints)
            self._findings_count = 0
            self._last_message = "Старт обстеження (2 камери → сервер)"

        self._thread = threading.Thread(
            target=self._run,
            args=(list(waypoints),),
            name=f"survey-{self.vehicle.id}",
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def _run(self, waypoints: List[Dict[str, float]]) -> None:
        cfg = load_monitoring_config()
        survey_cfg = cfg.get("survey") or {}
        dwell = float(survey_cfg.get("dwell_s", 2.5))
        min_conf = float(survey_cfg.get("min_confidence", 0.4))
        speed = float(survey_cfg.get("speed_m_s", 0.6))

        ctrl = self.vehicle.get_controller()
        vid = self.vehicle.id

        try:
            from simulator import fleet_registry

            for i, wp in enumerate(waypoints):
                if self._stop.is_set():
                    break

                with self._lock:
                    self.index = i
                    self._last_message = f"Точка {i + 1}/{len(waypoints)} · зйомка L/R"

                try:
                    ctrl.ensure_connected()
                    fleet_registry.halt_motion(vid)
                    ctrl.arm()
                    ctrl.goto_latlon(wp["lat"], wp["lon"], speed_m_s=speed)
                except Exception:
                    pass

                deadline = time.time() + 45.0
                while time.time() < deadline and not self._stop.is_set():
                    gps = _current_gps(self.vehicle)
                    if _gps_valid(gps):
                        from web.mission_runner import _haversine_m

                        d = _haversine_m(
                            float(gps["lat"]),
                            float(gps["lon"]),
                            wp["lat"],
                            wp["lon"],
                        )
                        if d <= 2.0:
                            break
                    time.sleep(0.2)

                fleet_registry.halt_motion(vid)
                try:
                    ctrl.stop()
                except Exception:
                    pass

                gps = _current_gps(self.vehicle)
                if not _gps_valid(gps):
                    gps = {"lat": wp["lat"], "lon": wp["lon"]}

                result = analyze_point(
                    crop=self.crop_id,
                    vehicle_id=vid,
                    lat=float(gps["lat"]),
                    lon=float(gps["lon"]),
                    source="survey",
                    vehicle=self.vehicle,
                )
                with self._lock:
                    self._last_message = result.message

                for det in result.detections:
                    if det.confidence < min_conf:
                        continue
                    append_finding(
                        new_finding(
                            crop=self.crop_id,
                            vehicle_id=vid,
                            lat=float(gps["lat"]),
                            lon=float(gps["lon"]),
                            issue_type=det.issue_type,
                            label=det.label,
                            confidence=det.confidence,
                            severity=det.severity,
                            source="survey",
                            note=result.model_status,
                            camera_side=det.camera_side or "",
                            capture_id=result.capture_id,
                        )
                    )
                    with self._lock:
                        self._findings_count += 1

                time.sleep(dwell)

        except Exception as exc:
            with self._lock:
                self._last_message = str(exc)
            self.phase = "aborted"
            return
        finally:
            try:
                fleet_registry.halt_motion(vid)
                ctrl.stop()
            except Exception:
                pass

        with self._lock:
            self.phase = "completed" if not self._stop.is_set() else "stopped"
            self._last_message = (
                f"Завершено: {self._findings_count} знахідок (віддалений аналіз)"
                if self.phase == "completed"
                else "Зупинено"
            )
        from monitoring.event_uplink import push_vehicle_event

        push_vehicle_event(
            self.vehicle,
            "monitoring_survey_end",
            detail=self._last_message,
            payload={
                "phase": self.phase,
                "findings_count": self._findings_count,
                "crop": self.crop_id,
            },
        )
