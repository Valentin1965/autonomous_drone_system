"""Маршрут по waypoints для одного vehicle у флоті."""

from __future__ import annotations

import math
import threading
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from web.fleet import get_fleet
from web.state import logger

if TYPE_CHECKING:
    from web.vehicle import Vehicle

# idle | running | at_last | returning | paused | aborted | completed


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6378137.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _gps_valid(gps: Optional[dict]) -> bool:
    if not gps:
        return False
    try:
        lat, lon = float(gps["lat"]), float(gps["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    return abs(lat) > 1e-4 or abs(lon) > 1e-4


def _current_gps(vehicle: "Vehicle", ctrl=None) -> dict:
    from simulator import fleet_registry

    sim = fleet_registry.get_position(vehicle.id)
    if sim:
        return dict(sim)
    if ctrl is None:
        ctrl = vehicle.get_controller()
    return dict((ctrl.get_status().get("gps") or {}))


def _halt_vehicle_motion(vehicle: "Vehicle", ctrl) -> None:
    from simulator import fleet_registry

    fleet_registry.halt_motion(vehicle.id)
    try:
        ctrl.stop()
    except Exception:
        pass


class MissionRunner:
    def __init__(self, vehicle: "Vehicle"):
        self.vehicle = vehicle
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._waypoints: List[Dict[str, float]] = []
        self.phase = "idle"
        self.index = 0
        self.total = 0
        self.speed_m_s = 1.0
        self.arrival_m = 2.5
        self._paused_return = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self.phase in ("running", "returning")

    def status(self) -> dict:
        with self._lock:
            st = {
                "active": self.phase in ("running", "returning"),
                "phase": self.phase,
                "index": self.index,
                "total": self.total,
                "can_return": self.phase == "at_last",
                "can_resume": self.phase == "paused",
                "vehicle_id": self.vehicle.id,
            }
        pos = _current_gps(self.vehicle, None)
        if _gps_valid(pos):
            st["vehicle"] = {
                "lat": float(pos["lat"]),
                "lon": float(pos["lon"]),
                "heading": float(pos.get("heading") or 0),
                "speed": float(pos.get("speed") or 0),
            }
        return st

    def start(self, waypoints: List[Dict[str, float]], speed_m_s: float = 1.0) -> dict:
        if not waypoints:
            raise ValueError("empty mission")
        if self.vehicle.control_mode != "autonomous":
            raise ValueError("vehicle not in autonomous mode")

        self.stop(wait=True)
        self._load_cfg()
        self.speed_m_s = max(0.1, float(speed_m_s))
        self._waypoints = list(waypoints)

        with self._lock:
            self.phase = "running"
            self.total = len(waypoints)
            self._stop.clear()

        self._thread = threading.Thread(
            target=self._run_forward,
            args=(list(waypoints),),
            name=f"mission-{self.vehicle.id}",
            daemon=True,
        )
        self._thread.start()
        st = self.status()
        st["start"] = {"lat": waypoints[0]["lat"], "lon": waypoints[0]["lon"]}
        return st

    def start_return(self, speed_m_s: Optional[float] = None) -> dict:
        with self._lock:
            if self.phase != "at_last":
                raise ValueError("Повернення доступне лише на останній точці маршруту")
            wps = list(self._waypoints)

        if len(wps) < 2:
            raise ValueError("Потрібно мінімум 2 точки для повернення")

        if speed_m_s is not None:
            self.speed_m_s = max(0.1, float(speed_m_s))

        path = list(reversed(wps[:-1]))

        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._stop.clear()

        with self._lock:
            self.phase = "returning"
            self.index = 0
            self.total = len(path)

        self._thread = threading.Thread(
            target=self._run_path,
            args=(path, True),
            name=f"mission-return-{self.vehicle.id}",
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def _load_cfg(self) -> None:
        cfg = get_fleet().load_config().get("mission", {})
        self.arrival_m = float(cfg.get("arrival_radius_m", 2.5))

    def update_route_waypoints(self, waypoints: List[Dict[str, float]]) -> None:
        with self._lock:
            if self.phase in ("running", "returning"):
                raise ValueError("Маршрут виконується — редагування недоступне")
            self._waypoints = list(waypoints)
            self.total = len(waypoints)
            if self.index >= len(waypoints):
                self.index = max(0, len(waypoints) - 1)

    def pause(self, wait: bool = True) -> None:
        with self._lock:
            prev = self.phase
            self._paused_return = prev == "returning"
            if prev in ("running", "returning"):
                self.phase = "paused"
        self._stop.set()
        try:
            ctrl = self.vehicle.get_controller()
            _halt_vehicle_motion(self.vehicle, ctrl)
        except Exception:
            from simulator import fleet_registry

            fleet_registry.halt_motion(self.vehicle.id)
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def resume(self, speed_m_s: Optional[float] = None) -> dict:
        with self._lock:
            if self.phase != "paused":
                raise ValueError("Маршрут не призупинено")
            if not self._waypoints:
                raise ValueError("empty mission")
            is_return = self._paused_return
            idx = self.index
            wps = list(self._waypoints)

        if speed_m_s is not None:
            self.speed_m_s = max(0.1, float(speed_m_s))

        if self.vehicle.control_mode != "autonomous":
            raise ValueError("Увімкніть автономний режим для цього дрона")

        self._stop.clear()
        if is_return:
            path = list(reversed(wps[:-1]))
            if len(path) < 1:
                raise ValueError("Потрібно мінімум 2 точки")
            with self._lock:
                self.phase = "returning"
                self.total = len(path)
            self._thread = threading.Thread(
                target=self._resume_path,
                args=(path, idx, True),
                daemon=True,
            )
        else:
            with self._lock:
                self.phase = "running"
                self.total = len(wps)
            idx = max(1, min(idx, len(wps) - 1)) if len(wps) > 1 else 0
            self._thread = threading.Thread(
                target=self._resume_path,
                args=(wps, idx, False),
                daemon=True,
            )
        self._thread.start()
        return self.status()

    def stop(self, wait: bool = True) -> None:
        self._stop.set()
        with self._lock:
            if self.phase not in ("idle",):
                self.phase = "aborted"
        try:
            ctrl = self.vehicle.get_controller()
            _halt_vehicle_motion(self.vehicle, ctrl)
        except Exception:
            from simulator import fleet_registry

            fleet_registry.halt_motion(self.vehicle.id)
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def _run_forward(self, waypoints: List[Dict[str, float]]) -> None:
        from simulator import fleet_registry

        ctrl = self.vehicle.get_controller()
        vid = self.vehicle.id
        try:
            ctrl.ensure_connected()
            _halt_vehicle_motion(self.vehicle, ctrl)
            fleet_registry.snap_to(waypoints[0]["lat"], waypoints[0]["lon"], vid)

            if len(waypoints) == 1:
                ctrl.arm()
                with self._lock:
                    self.index = 0
                self._set_phase("at_last")
                _halt_vehicle_motion(self.vehicle, ctrl)
                return

            ctrl.arm()
            with self._lock:
                self.index = 1
            self._goto(ctrl, waypoints[1])
            self._follow_path(ctrl, waypoints, start_index=1, is_return=False)
        except Exception as exc:
            logger.exception("mission forward failed [%s]: %s", vid, exc)
            self._set_phase("aborted")
            _halt_vehicle_motion(self.vehicle, ctrl)

    def _resume_path(
        self,
        waypoints: List[Dict[str, float]],
        start_index: int,
        is_return: bool,
    ) -> None:
        ctrl = self.vehicle.get_controller()
        try:
            ctrl.ensure_connected()
            _halt_vehicle_motion(self.vehicle, ctrl)
            ctrl.arm()
            with self._lock:
                self.index = start_index
            if start_index < len(waypoints):
                self._goto(ctrl, waypoints[start_index])
            self._follow_path(ctrl, waypoints, start_index=start_index, is_return=is_return)
        except Exception as exc:
            logger.exception("mission resume failed [%s]: %s", self.vehicle.id, exc)
            self._set_phase("aborted")
            _halt_vehicle_motion(self.vehicle, ctrl)

    def _run_path(self, waypoints: List[Dict[str, float]], is_return: bool) -> None:
        ctrl = self.vehicle.get_controller()
        try:
            ctrl.ensure_connected()
            _halt_vehicle_motion(self.vehicle, ctrl)
            ctrl.arm()
            with self._lock:
                self.index = 0
            self._goto(ctrl, waypoints[0])
            self._follow_path(ctrl, waypoints, start_index=0, is_return=is_return)
        except Exception as exc:
            logger.exception("mission path failed [%s]: %s", self.vehicle.id, exc)
            self._set_phase("aborted")
            _halt_vehicle_motion(self.vehicle, ctrl)

    def _follow_path(
        self,
        ctrl,
        waypoints: List[Dict[str, float]],
        start_index: int,
        is_return: bool,
    ) -> None:
        from simulator import fleet_registry

        mcfg = get_fleet().load_config().get("mission", {})
        poll = float(mcfg.get("poll_interval_s", 0.2))
        goto_interval = float(mcfg.get("goto_retry_s", 1.0))
        n = len(waypoints)
        vid = self.vehicle.id

        with self._lock:
            self.index = start_index

        while not self._stop.is_set():
            if get_fleet().emergency_stop:
                self._set_phase("aborted")
                _halt_vehicle_motion(self.vehicle, ctrl)
                return

            with self._lock:
                idx = self.index

            if idx >= n:
                time.sleep(poll)
                continue

            wp = waypoints[idx]
            gps = _current_gps(self.vehicle, ctrl)
            if not _gps_valid(gps):
                time.sleep(poll)
                continue

            dist = _haversine_m(
                float(gps["lat"]), float(gps["lon"]),
                wp["lat"], wp["lon"],
            )

            if dist <= self.arrival_m:
                next_idx = idx + 1

                if not is_return and next_idx >= n:
                    fleet_registry.snap_to(wp["lat"], wp["lon"], vid)
                    with self._lock:
                        self.index = len(self._waypoints) - 1
                    _halt_vehicle_motion(self.vehicle, ctrl)
                    self._stop.set()
                    self._set_phase("at_last")
                    return

                if is_return and next_idx >= n:
                    if waypoints:
                        fleet_registry.snap_to(
                            waypoints[-1]["lat"], waypoints[-1]["lon"], vid
                        )
                    _halt_vehicle_motion(self.vehicle, ctrl)
                    self._stop.set()
                    self._set_phase("completed")
                    return

                with self._lock:
                    self.index = next_idx
                self._goto(ctrl, waypoints[next_idx])
            elif time.time() - getattr(self, "_last_goto", 0) > goto_interval:
                self._goto(ctrl, wp)

            time.sleep(poll)

    def _goto(self, ctrl, wp: Dict[str, float]) -> None:
        with self._lock:
            if self.phase in ("at_last", "completed", "aborted", "paused", "idle"):
                return
        if self._stop.is_set():
            return
        ctrl.goto_latlon(wp["lat"], wp["lon"], speed_m_s=self.speed_m_s)
        self._last_goto = time.time()

    def _set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = phase


def get_mission_runner(vehicle_id: Optional[str] = None) -> MissionRunner:
    return get_fleet().get_vehicle(vehicle_id).mission_runner


class _MissionRunnerProxy:
    """Зворотна сумісність: mission_runner → обраний дрон."""

    def __getattr__(self, name):
        return getattr(get_mission_runner(), name)


mission_runner = _MissionRunnerProxy()
