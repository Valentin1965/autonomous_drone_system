"""Один ground rover у флоті."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from utils.logger import setup_logger

logger = setup_logger("drone_vehicle")


class Vehicle:
    def __init__(
        self,
        vehicle_id: str,
        name: str,
        mavlink_connection: str,
        color: str = "#ff9800",
        sim_bind: Optional[str] = None,
        start_lat: Optional[float] = None,
        start_lon: Optional[float] = None,
        video_file: Optional[str] = None,
        active: bool = True,
    ):
        self.id = vehicle_id
        self.name = name
        self.mavlink_connection = mavlink_connection
        self.color = color
        self.sim_bind = sim_bind
        if start_lat is None or start_lon is None:
            from config.geo_defaults import DEFAULT_LAT, DEFAULT_LON

            start_lat = start_lat if start_lat is not None else DEFAULT_LAT
            start_lon = start_lon if start_lon is not None else DEFAULT_LON
        self.start_lat = start_lat
        self.start_lon = start_lon
        self.video_file = (video_file or "").strip() or None
        self.active = bool(active)
        self.mission_waypoints: List[Dict[str, float]] = []
        self.mission_draft: Optional[Dict[str, Any]] = None
        self.mission_route_committed: bool = False
        from web.mission_record import default_record

        self.mission_record: Dict[str, Any] = default_record()
        self.control_mode = "autonomous"
        self.sprayer_active = False
        self._controller = None
        self._lock = threading.Lock()
        from web.mission_runner import MissionRunner

        self.mission_runner = MissionRunner(self)

    def set_mission_draft(
        self,
        waypoints: List[dict],
        *,
        planning: Optional[dict] = None,
        segments: Optional[list] = None,
    ) -> None:
        from web.mission_route import normalize_route_wp

        self.mission_draft = {
            "waypoints": [normalize_route_wp(w) for w in waypoints if w.get("lat") is not None],
            "planning": planning,
            "segments": segments,
        }
        self.mission_route_committed = False

    def clear_mission_draft(self) -> None:
        self.mission_draft = None

    def get_execution_waypoints(self) -> List[Dict[str, Any]]:
        """Точки для польоту: чернетка до фіксації, інакше збережений маршрут."""
        if self.mission_draft and not self.mission_route_committed:
            return list(self.mission_draft.get("waypoints") or [])
        return list(self.mission_waypoints)

    def commit_route_with_actual(
        self,
        planned_waypoints: List[dict],
        actual_by_index: Dict[int, dict],
    ) -> List[Dict[str, float]]:
        """Запис на сервер: реальні GPS де є, решта — з плану."""
        from web.mission_route import normalize_nav_wp, normalize_route_wp

        committed: List[Dict[str, Any]] = []
        for i, wp in enumerate(planned_waypoints):
            if i in actual_by_index:
                base = normalize_nav_wp(actual_by_index[i])
            else:
                base = normalize_nav_wp(wp)
            if wp.get("role") is not None:
                base["role"] = wp.get("role")
            if wp.get("row_index") is not None:
                base["row_index"] = wp.get("row_index")
            committed.append(base)
        self.mission_waypoints = [
            {"lat": w["lat"], "lon": w["lon"]} for w in committed
        ]
        self.mission_route_committed = True
        planning = (self.mission_draft or {}).get("planning")
        if planning and isinstance(self.mission_record, dict):
            self.mission_record["route_planning"] = planning
        self.mission_draft = None
        return list(self.mission_waypoints)

    def reset_controller(self) -> None:
        """Скинути MAVLink-клієнт (після зміни порту / складу флоту)."""
        with self._lock:
            if self._controller is not None:
                try:
                    self._controller._disconnect()
                except Exception:
                    pass
            self._controller = None

    def get_controller(self):
        if self._controller is None:
            with self._lock:
                if self._controller is None:
                    from mavlink.ground_controller import GroundController

                    from web.fleet import get_fleet

                    cfg = get_fleet().load_config()
                    mavlink_cfg = cfg.get("mavlink", {})
                    offboard_cfg = cfg.get("offboard", {})
                    vehicle_cfg = cfg.get("vehicle", {})
                    self._controller = GroundController(
                        connection_string=self.mavlink_connection,
                        rate_hz=offboard_cfg.get("rate_hz", 20),
                        default_frame=vehicle_cfg.get("default_frame", "body"),
                        heartbeat_timeout=mavlink_cfg.get("heartbeat_timeout", 5),
                        logger=logger,
                        vehicle_id=self.id,
                    )
        return self._controller

    def get_control_mode(self) -> str:
        return self.control_mode

    def set_control_mode(self, mode: str) -> None:
        if mode not in ("autonomous", "manual"):
            raise ValueError("mode must be autonomous or manual")
        self.control_mode = mode

    def status_summary(self) -> dict:
        from simulator import fleet_registry

        st: dict = {"connected": False, "gps": {}, "armed": False}
        sim_pos = fleet_registry.get_position(self.id)
        if sim_pos:
            st["connected"] = True
            st["gps"] = dict(sim_pos)
            st["gps_source"] = "simulator"
            st["armed"] = bool(sim_pos.get("armed", False))
        else:
            try:
                ctrl_st = self.get_controller().get_status()
                st["connected"] = bool(ctrl_st.get("connected"))
                if ctrl_st.get("gps"):
                    st["gps"] = dict(ctrl_st["gps"])
                    st["gps_source"] = ctrl_st.get("gps_source", "mavlink")
                st["armed"] = ctrl_st.get("armed", False)
                st["heartbeat_age_s"] = ctrl_st.get("heartbeat_age_s")
            except Exception as e:
                st["connected"] = False
                st["link_error"] = str(e)
        mr = self.mission_runner.status()
        try:
            from web.tracker_service import fleet_cv_status

            cv_st = fleet_cv_status(self.id)
        except Exception:
            cv_st = {"connected": False, "video_file": self.video_file}
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "mavlink_connection": self.mavlink_connection,
            "control_mode": self.control_mode,
            "connected": st.get("connected", False),
            "armed": st.get("armed", False),
            "gps": st.get("gps") or {},
            "heartbeat_age_s": st.get("heartbeat_age_s"),
            "mission": mr,
            "waypoint_count": len(self.get_execution_waypoints()),
            "route_committed": self.mission_route_committed,
            "has_route_draft": bool(
                self.mission_draft and not self.mission_route_committed
            ),
            "sprayer_active": self.sprayer_active,
            "video_file": self.video_file,
            "cv": cv_st,
            "active": self.active,
        }
