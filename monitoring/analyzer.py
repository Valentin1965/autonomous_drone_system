"""Зйомка двома камерами + аналіз на віддаленому сервері."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from monitoring.capture import capture_stereo
from monitoring.config_loader import load_monitoring_config
from monitoring.remote_client import RemoteAnalysisResult, analyze_stereo_remote

if TYPE_CHECKING:
    from web.vehicle import Vehicle


def analyze_point(
    *,
    crop: str,
    vehicle_id: str,
    lat: float,
    lon: float,
    source: str = "survey",
    vehicle: Optional["Vehicle"] = None,
) -> RemoteAnalysisResult:
    """
    Зняти лівий/правий кадр і відправити на сервер YOLO (або mock).
    На rover Ultralytics не викликається.
    """
    cfg = load_monitoring_config()
    demo = bool(cfg.get("demo_findings_in_sim", False))
    vid = vehicle_id or (vehicle.id if vehicle is not None else "rover_1")
    stereo = capture_stereo(vid)
    errors = []
    if stereo.left.error:
        errors.append(f"left: {stereo.left.error}")
    if stereo.right.error:
        errors.append(f"right: {stereo.right.error}")

    context: Optional[Dict[str, Any]] = None
    if vehicle is not None:
        from monitoring.station_context import build_vehicle_context

        context = {"vehicle": build_vehicle_context(vehicle), "source": source}

    result = analyze_stereo_remote(
        stereo,
        crop=crop,
        vehicle_id=vehicle_id,
        lat=lat,
        lon=lon,
        source=source,
        demo_sim=demo,
        context=context,
    )
    if errors and not result.remote_ok:
        result.message = "; ".join(errors) + (" · " + result.message if result.message else "")
    elif errors:
        result.message = (result.message or "") + " · " + "; ".join(errors)
    return result
