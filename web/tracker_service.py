"""Lazy CV tracker with in-process MotionBridge (per fleet vehicle video/camera)."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

_tracker = None
_tracker_vehicle_id: Optional[str] = None


def cv_mode() -> str:
    """local | onboard (CV на RPi)."""
    try:
        from web.state import drone_state

        cfg = drone_state.load_config()
        mode = str((cfg.get("cv") or {}).get("mode") or "local").strip().lower()
        return mode or "local"
    except Exception:
        return "local"


def cv_config_for_vehicle(
    video_file: Optional[str] = None,
    vehicle_id: Optional[str] = None,
) -> dict:
    """Базовий cv.yaml + абсолютний шлях до відео дрона."""
    from cv.tracker import load_cv_config

    cfg = dict(load_cv_config())
    resolved = None
    if vehicle_id:
        from web.fleet_video import resolve_vehicle_video_path

        resolved = resolve_vehicle_video_path(vehicle_id, video_file)
    elif video_file:
        from web.fleet_video import project_root, resolve_media_path

        resolved = resolve_media_path(str(video_file).strip(), project_root())
    if resolved:
        cfg["video_file"] = str(resolved)
        cfg["source"] = "video"
    elif video_file:
        cfg["video_file"] = video_file
        cfg["source"] = "video"
    return cfg


def video_info_for_vehicle(v) -> Dict[str, Any]:
    """Статус відеофайлу дрона (імітація камери до підключення заліза)."""
    from web.fleet_video import video_discovery_payload

    return video_discovery_payload(v.id, v.video_file)


def fleet_cv_status(vehicle_id: str) -> Dict[str, Any]:
    from web.fleet import get_fleet

    v = get_fleet().get_vehicle(vehicle_id)
    info = video_info_for_vehicle(v)
    connected = is_running() and _tracker_vehicle_id == vehicle_id
    out = {
        "vehicle_id": vehicle_id,
        "connected": connected,
        "mode": cv_mode(),
        **info,
    }
    if connected and _tracker is not None:
        try:
            pub = _tracker.get_public_status()
            out["source"] = pub.get("source")
            out["planner"] = pub.get("planner")
            out["nav_source"] = pub.get("nav_source")
            if pub.get("video_file"):
                out["video_resolved"] = pub.get("video_file")
        except Exception:
            pass
    return out


def get_tracker(vehicle_id: Optional[str] = None, recreate: bool = False):
    global _tracker, _tracker_vehicle_id
    if cv_mode() == "onboard":
        raise RuntimeError(
            "CV працює на борту (RPi). На GCS локальний трекер вимкнено (cv.mode=onboard)."
        )
    from web.fleet import get_fleet
    from cv.tracker import YOLOSegmentationTracker
    from web.motion_bridge import MotionBridge
    from web.state import drone_state

    fleet = get_fleet()
    vid = vehicle_id or fleet.selected_id
    v = fleet.get_vehicle(vid)
    if recreate or (_tracker is not None and _tracker_vehicle_id != vid):
        reset_tracker()
    if _tracker is None:
        cfg = cv_config_for_vehicle(v.video_file, vehicle_id=vid)
        source = os.environ.get("CV_SOURCE", "").strip().lower() or None
        _tracker = YOLOSegmentationTracker(
            config=cfg,
            motion=MotionBridge(),
            source=source if source else None,
        )
        _tracker.set_emergency_check(lambda: drone_state.emergency_stop)
        _tracker_vehicle_id = vid
        vf = cfg.get("video_file") or v.video_file
        if vf:
            print(f"[CV] Флот [{vid}] відео: {vf}")
    return _tracker


def reset_tracker():
    global _tracker, _tracker_vehicle_id
    if _tracker is not None:
        try:
            _tracker.stop()
        except Exception:
            pass
    _tracker = None
    _tracker_vehicle_id = None


def on_fleet_vehicle_selected(new_id: str, old_id: Optional[str]) -> None:
    """Якщо CV підключено до старого дрона — перемкнути потік на нового обраного."""
    if not new_id or new_id == old_id:
        return
    if not is_running() or _tracker_vehicle_id != old_id:
        return
    try:
        connect_cv(new_id, select_vehicle=False)
    except Exception as e:
        print(f"[CV] Помилка перемикання на [{new_id}]: {e}")


def connect_cv(vehicle_id: str, select_vehicle: bool = True) -> Dict[str, Any]:
    """Підключити відео/камеру для конкретного дрона (dev: .mp4, поле: потік з борту)."""
    from web.fleet import get_fleet
    from web.preflight import assert_ready_for_cv
    from web.vehicle_prep import prepare_for_motion

    if cv_mode() == "onboard":
        return {
            "status": "error",
            "mode": "onboard",
            "message": "CV на борту (RPi). Підключення відео на GCS недоступне.",
        }

    fleet = get_fleet()
    v = fleet.get_vehicle(vehicle_id)
    info = video_info_for_vehicle(v)

    if is_running() and _tracker_vehicle_id == vehicle_id:
        return {
            "status": "already_connected",
            "vehicle_id": vehicle_id,
            **info,
            **fleet_cv_status(vehicle_id),
        }

    if is_running():
        reset_tracker()

    if select_vehicle and fleet.selected_id != vehicle_id:
        fleet.select(vehicle_id)

    prepare_for_motion(v)
    st = v.get_controller().get_status()
    pre = assert_ready_for_cv(v, mavlink_status=st)
    if pre:
        return {"status": "error", "vehicle_id": vehicle_id, **info, **pre}

    try:
        tracker = get_tracker(vehicle_id, recreate=True)
        result = tracker.start()
    except Exception as e:
        return {
            "status": "error",
            "vehicle_id": vehicle_id,
            "message": str(e),
            **info,
        }

    if isinstance(result, dict) and result.get("status") == "error":
        reset_tracker()
        return {"vehicle_id": vehicle_id, **info, **result}

    src = (result or {}).get("source", "") if isinstance(result, dict) else ""
    msg_parts = [f"Відео [{v.name}]"]
    if info.get("video_available"):
        msg_parts.append(f"→ {info.get('video_label') or info.get('video_file')}")
    elif info.get("will_use_synthetic"):
        missing = info.get("video_label") or info.get("video_file") or "файл"
        msg_parts.append(f"({missing} не знайдено — синтетичний ряд)")
    if src:
        msg_parts.append(f"· {src}")

    out = {
        "status": (result or {}).get("status", "started")
        if isinstance(result, dict)
        else "started",
        "vehicle_id": vehicle_id,
        "message": " ".join(msg_parts),
        **info,
        **((result or {}) if isinstance(result, dict) else {}),
    }
    out["connected"] = is_running()
    return out


def disconnect_cv(vehicle_id: Optional[str] = None) -> Dict[str, Any]:
    """Відключити CV-потік (для одного дрона або поточного)."""
    vid = vehicle_id or _tracker_vehicle_id
    if not is_running():
        return {"status": "not_connected", "vehicle_id": vid}
    if vehicle_id and _tracker_vehicle_id != vehicle_id:
        return {
            "status": "not_connected",
            "vehicle_id": vehicle_id,
            "message": f"CV активний на {_tracker_vehicle_id}, не на {vehicle_id}",
        }
    reset_tracker()
    return {"status": "disconnected", "vehicle_id": vid}


def is_running() -> bool:
    return bool(_tracker and _tracker.running)


def tracker_vehicle_id() -> Optional[str]:
    return _tracker_vehicle_id


def get_jpeg_frame():
    if _tracker is None:
        return None
    return _tracker.get_jpeg_frame()


def get_cv_status() -> dict:
    mode = cv_mode()
    if mode == "onboard":
        return {
            "running": False,
            "planner": None,
            "nav_source": None,
            "mode": "onboard",
            "message": "CV на борту (RPi). Локальний трекер на GCS заблоковано.",
        }
    if _tracker is None:
        st = {"running": False, "planner": None, "nav_source": None, "mode": mode}
        try:
            from web.fleet import get_fleet

            v = get_fleet().selected
            if v.video_file:
                st["video_file"] = v.video_file
                st["vehicle_id"] = v.id
        except Exception:
            pass
        return st
    st = _tracker.get_public_status()
    st["mode"] = mode
    if _tracker_vehicle_id:
        st["vehicle_id"] = _tracker_vehicle_id
    return st


def hazard_blocks_motion(vehicle_id: Optional[str] = None) -> bool:
    """True якщо CV бачить перешкоду — лише для дрона, на якому увімкнено CV."""
    if _tracker is None or not _tracker.running:
        return False
    if vehicle_id and _tracker_vehicle_id and vehicle_id != _tracker_vehicle_id:
        return False
    return _tracker.is_hazard_stop_active()
