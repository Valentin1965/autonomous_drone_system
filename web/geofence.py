"""Геозона (bbox) — обмеження робочої зони на карті."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_BOUNDS: Optional[Tuple[float, float, float, float]] = None
_ENABLED: bool = False
_OPERATOR_SET: bool = False

_MIN_SPAN_DEG = 0.00015  # ~15 м


def _merge_config() -> dict:
    from web.state import drone_state

    cfg = dict(drone_state.load_config().get("geofence") or {})
    try:
        from web.geofence_store import load_runtime

        runtime = load_runtime()
        if runtime is not None:
            cfg.update(runtime)
    except Exception:
        pass
    return cfg


def _load() -> None:
    global _BOUNDS, _ENABLED, _OPERATOR_SET
    if _BOUNDS is not None:
        return

    cfg = _merge_config()
    _OPERATOR_SET = bool(cfg.get("operator_set", False)) or _has_runtime_file()
    _ENABLED = bool(cfg.get("enabled", False))
    try:
        _BOUNDS = normalize_bounds(
            float(cfg["min_lat"]),
            float(cfg["max_lat"]),
            float(cfg["min_lon"]),
            float(cfg["max_lon"]),
        )
    except (KeyError, TypeError, ValueError):
        _ENABLED = False
        _BOUNDS = None


def _has_runtime_file() -> bool:
    from web.geofence_store import RUNTIME_PATH

    return RUNTIME_PATH.is_file()


def normalize_bounds(
    lat1: float, lat2: float, lon1: float, lon2: float
) -> Tuple[float, float, float, float]:
    min_lat = min(float(lat1), float(lat2))
    max_lat = max(float(lat1), float(lat2))
    min_lon = min(float(lon1), float(lon2))
    max_lon = max(float(lon1), float(lon2))
    if max_lat - min_lat < _MIN_SPAN_DEG or max_lon - min_lon < _MIN_SPAN_DEG:
        raise ValueError("Геозона замала — оберіть більший прямокутник")
    return min_lat, max_lat, min_lon, max_lon


def reload() -> None:
    """Скинути кеш після зміни config (тести / API)."""
    global _BOUNDS
    _BOUNDS = None
    _load()


def is_enabled() -> bool:
    _load()
    return _ENABLED and _BOUNDS is not None


def operator_configured() -> bool:
    _load()
    return is_enabled()


def bounds() -> Optional[Tuple[float, float, float, float]]:
    _load()
    return _BOUNDS


def public_config() -> Dict[str, Any]:
    _load()
    if not is_enabled() or _BOUNDS is None:
        return {"enabled": False, "operator_set": _OPERATOR_SET}
    min_lat, max_lat, min_lon, max_lon = _BOUNDS
    return {
        "enabled": True,
        "operator_set": _OPERATOR_SET,
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }


def set_bounds(lat1: float, lat2: float, lon1: float, lon2: float) -> Dict[str, Any]:
    """Зберегти геозону оператора."""
    min_lat, max_lat, min_lon, max_lon = normalize_bounds(lat1, lat2, lon1, lon2)
    payload = {
        "enabled": True,
        "operator_set": True,
        "min_lat": min_lat,
        "max_lat": max_lat,
        "min_lon": min_lon,
        "max_lon": max_lon,
    }
    from web.geofence_store import save_runtime

    save_runtime(payload)
    reload()
    return public_config()


def set_disabled() -> Dict[str, Any]:
    from web.geofence_store import save_runtime

    save_runtime({"enabled": False, "operator_set": True})
    reload()
    return public_config()


def contains(lat: float, lon: float) -> bool:
    if not is_enabled() or _BOUNDS is None:
        return True
    min_lat, max_lat, min_lon, max_lon = _BOUNDS
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def check_position(lat: float, lon: float) -> Tuple[bool, str]:
    if not is_enabled():
        return True, ""
    if contains(lat, lon):
        return True, ""
    b = _BOUNDS
    return False, (
        f"Позиція ({lat:.5f}, {lon:.5f}) поза геозоною "
        f"[{b[0]:.5f}…{b[1]:.5f}] × [{b[2]:.5f}…{b[3]:.5f}]"
    )


def check_waypoints(waypoints: List[Dict[str, float]]) -> Tuple[bool, str]:
    if not is_enabled() or not waypoints:
        return True, ""
    for i, wp in enumerate(waypoints):
        try:
            lat, lon = float(wp["lat"]), float(wp["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        ok, msg = check_position(lat, lon)
        if not ok:
            return False, f"Точка {i + 1}: {msg}"
    return True, ""


def breach_message() -> str:
    return "Вихід за геозону — рух зупинено"
