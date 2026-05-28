"""Пошук відеофайлів для дронів у assets/videos (файли в .gitignore, на диску мають бути)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

_VIDEO_GLOBS = (
    "*.mp4",
    "*.MP4",
    "*.avi",
    "*.AVI",
    "*.mov",
    "*.MOV",
    "*.mkv",
    "*.MKV",
    "*.webm",
    "*.WEBM",
)


def project_root() -> Path:
    try:
        from config.config_paths import project_root as root

        return root()
    except Exception:
        return Path(__file__).resolve().parent.parent


def videos_directory() -> Path:
    return project_root() / "assets" / "videos"


def list_assets_videos() -> List[Path]:
    """Усі відео в assets/videos (на диску WSL, навіть якщо не в git)."""
    vdir = videos_directory()
    if not vdir.is_dir():
        return []
    found: List[Path] = []
    seen = set()
    for pattern in _VIDEO_GLOBS:
        for p in vdir.glob(pattern):
            key = str(p.resolve())
            if key not in seen and p.is_file():
                seen.add(key)
                found.append(p.resolve())
    return sorted(found, key=lambda p: p.name.lower())


def resolve_media_path(path_str: str, root: Optional[Path] = None) -> Optional[Path]:
    root = root or project_root()
    p = Path(path_str)
    if p.is_file():
        return p.resolve()
    candidate = root / path_str
    if candidate.is_file():
        return candidate.resolve()
    return None


def rover_index_from_id(vehicle_id: str) -> int:
    try:
        return max(0, int(str(vehicle_id).rsplit("_", 1)[-1]) - 1)
    except (TypeError, ValueError):
        return 0


def resolve_vehicle_video_path(
    vehicle_id: str,
    video_file: Optional[str] = None,
) -> Optional[Path]:
    """
    Шлях до відео дрона:
    1) video_file з конфігу (відносний від кореня проєкту)
    2) default vineyard_demo*.mp4 за індексом rover_N
    3) N-й файл у assets/videos (за алфавітом)
    """
    from web.fleet_config import default_fleet_video_file

    root = project_root()
    idx = rover_index_from_id(vehicle_id)
    candidates: List[str] = []
    if video_file:
        candidates.append(str(video_file).strip())
    candidates.append(default_fleet_video_file(idx))

    for rel in candidates:
        if not rel:
            continue
        hit = resolve_media_path(rel, root)
        if hit:
            return hit

    files = list_assets_videos()
    if not files:
        return None

    # Точне ім'я за замовчуванням (vineyard_demo1 для rover_2)
    want = Path(default_fleet_video_file(idx)).name.lower()
    for f in files:
        if f.name.lower() == want:
            return f

    if idx < len(files):
        return files[idx]

    return files[0]


def video_discovery_payload(vehicle_id: str, video_file: Optional[str] = None) -> dict:
    """Статус відео для API / флоту."""
    vdir = videos_directory()
    resolved = resolve_vehicle_video_path(vehicle_id, video_file)
    files = list_assets_videos()
    label = (video_file or "").split("/")[-1] if video_file else ""
    available = resolved is not None and resolved.is_file()
    cfg_fallback = True
    try:
        from cv.tracker import load_cv_config

        cfg_fallback = bool(load_cv_config().get("fallback_to_synthetic", False))
    except Exception:
        pass
    return {
        "video_file": video_file,
        "video_label": label or (resolved.name if resolved else None),
        "video_resolved": str(resolved) if resolved else None,
        "video_dir": str(vdir),
        "video_dir_exists": vdir.is_dir(),
        "videos_in_dir": [f.name for f in files],
        "videos_count": len(files),
        "video_available": available,
        "video_missing": bool(video_file or files) and not available,
        "will_use_synthetic": (not available) and cfg_fallback,
    }
