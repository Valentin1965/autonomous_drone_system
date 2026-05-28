"""Сервіс моніторингу — 2 камери, віддалений YOLO, без локального CV ряду."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from monitoring.analyzer import analyze_point
from monitoring.cameras import get_camera_rig
from monitoring.config_loader import load_monitoring_config
from monitoring.models import list_crops_public, new_finding
from monitoring.remote_client import check_remote_health
from monitoring.store import append_finding, clear_findings, query_findings
from monitoring.survey_runner import SurveyRunner

_service: Optional["MonitoringService"] = None
_lock = threading.Lock()


class MonitoringService:
    def __init__(self):
        self._crop = load_monitoring_config().get("default_crop", "vineyard")
        self._runners: Dict[str, SurveyRunner] = {}

    def reload_config(self) -> None:
        load_monitoring_config(reload=True)
        get_camera_rig(reload=True)

    def get_crop(self) -> str:
        return self._crop

    def set_crop(self, crop_id: str) -> str:
        cfg = load_monitoring_config()
        crops = cfg.get("crops") or {}
        if crop_id not in crops:
            raise ValueError(f"unknown crop: {crop_id}")
        self._crop = crop_id
        return crop_id

    def _runner_for(self, vehicle) -> SurveyRunner:
        vid = vehicle.id
        if vid not in self._runners:
            self._runners[vid] = SurveyRunner(vehicle, self._crop)
        else:
            self._runners[vid].crop_id = self._crop
        return self._runners[vid]

    def public_config(self) -> Dict[str, Any]:
        from monitoring.rpi_uplink import is_rpi_source, uplink_source
        from monitoring.station_config import station_meta

        cfg = load_monitoring_config()
        rcfg = cfg.get("remote") or {}
        uplink = cfg.get("uplink") or {}
        st = station_meta()
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "crop": self._crop,
            "crops": list_crops_public(cfg),
            "cameras": get_camera_rig().status(),
            "station": {
                "id": st["station_id"],
                "operator": st["operator"],
            },
            "uplink": {
                "source": uplink_source(),
                "rpi": uplink.get("rpi") or {},
                "is_rpi": is_rpi_source(),
            },
            "remote": {
                "enabled": bool(rcfg.get("enabled", True)),
                "mode": rcfg.get("mode", "remote"),
                "base_url": rcfg.get("base_url", ""),
                "analyze_path": rcfg.get("analyze_path", ""),
            },
            "demo_findings_in_sim": bool(cfg.get("demo_findings_in_sim", False)),
            "survey": cfg.get("survey") or {},
            "architecture": "dual_camera_remote_yolo",
        }

    def status(self, vehicle_id: Optional[str] = None) -> Dict[str, Any]:
        cfg = load_monitoring_config()
        health = check_remote_health()
        spray_cov: Dict[str, Any] = {}
        try:
            from monitoring.spray_coverage import vehicle_summary

            if vehicle_id:
                spray_cov = vehicle_summary(vehicle_id)
        except Exception:
            pass
        out: Dict[str, Any] = {
            "enabled": bool(cfg.get("enabled", True)),
            "crop": self._crop,
            "findings_total": len(query_findings(limit=10_000)),
            "cameras": get_camera_rig().status(),
            "remote": health,
            "spray_coverage": spray_cov,
            "surveys": {},
        }
        for vid, runner in self._runners.items():
            if vehicle_id and vid != vehicle_id:
                continue
            out["surveys"][vid] = runner.status()
        return out

    def list_findings(
        self,
        *,
        vehicle_id: Optional[str] = None,
        crop: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        return query_findings(vehicle_id=vehicle_id, crop=crop or None, limit=limit)

    def clear(
        self,
        *,
        vehicle_id: Optional[str] = None,
        crop: Optional[str] = None,
    ) -> int:
        return clear_findings(vehicle_id=vehicle_id, crop=crop)

    def start_survey(self, vehicle, waypoints: Optional[List[Dict[str, float]]] = None) -> dict:
        cfg = load_monitoring_config()
        if not cfg.get("enabled", True):
            raise ValueError("Моніторинг вимкнено в config/monitoring.yaml")

        mr = vehicle.mission_runner
        if mr.active:
            raise ValueError("Спочатку зупиніть GPS-маршрут (■ Стоп)")

        wps = list(waypoints or vehicle.mission_waypoints or [])
        if len(wps) < 1:
            raise ValueError("Додайте точки маршруту для обстеження")

        from monitoring.event_uplink import push_vehicle_event

        runner = self._runner_for(vehicle)
        runner.crop_id = self._crop
        push_vehicle_event(
            vehicle,
            "monitoring_survey_start",
            detail=f"{len(wps)} точок, crop={self._crop}",
            payload={"waypoint_count": len(wps), "crop": self._crop},
        )
        return runner.start(wps)

    def stop_survey(self, vehicle) -> dict:
        runner = self._runners.get(vehicle.id)
        if runner:
            runner.stop()
            return runner.status()
        return {"active": False, "phase": "idle", "vehicle_id": vehicle.id}

    def sample_now(self, vehicle) -> Dict[str, Any]:
        """Зразок: 2 камери → віддалений сервер, без руху."""
        gps = _current_gps(vehicle)
        result = analyze_point(
            crop=self._crop,
            vehicle_id=vehicle.id,
            lat=float(gps.get("lat", 0)),
            lon=float(gps.get("lon", 0)),
            source="manual",
            vehicle=vehicle,
        )

        saved = []
        min_conf = float(
            (load_monitoring_config().get("survey") or {}).get("min_confidence", 0.4)
        )
        for det in result.detections:
            if det.confidence < min_conf:
                continue
            rec = append_finding(
                new_finding(
                    crop=self._crop,
                    vehicle_id=vehicle.id,
                    lat=float(gps.get("lat", 0)),
                    lon=float(gps.get("lon", 0)),
                    issue_type=det.issue_type,
                    label=det.label,
                    confidence=det.confidence,
                    severity=det.severity,
                    source="manual",
                    note=result.model_status,
                    camera_side=det.camera_side or "",
                    capture_id=result.capture_id,
                )
            )
            saved.append(rec)

        return {
            "vehicle_id": vehicle.id,
            "crop": self._crop,
            "model_status": result.model_status,
            "message": result.message,
            "remote_ok": result.remote_ok,
            "capture_id": result.capture_id,
            "findings": saved,
            "gps": gps,
        }


def _current_gps(vehicle) -> dict:
    from simulator import fleet_registry

    sim = fleet_registry.get_position(vehicle.id)
    if sim:
        return dict(sim)
    return dict(vehicle.get_controller().get_status().get("gps") or {})


def get_monitoring_service() -> MonitoringService:
    global _service
    with _lock:
        if _service is None:
            _service = MonitoringService()
        return _service


def reset_monitoring_service() -> None:
    global _service
    with _lock:
        if _service is not None:
            try:
                get_camera_rig().release()
            except Exception:
                pass
        _service = None
