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
        start_lat: float = 50.4501,
        start_lon: float = 30.5234,
    ):
        self.id = vehicle_id
        self.name = name
        self.mavlink_connection = mavlink_connection
        self.color = color
        self.sim_bind = sim_bind
        self.start_lat = start_lat
        self.start_lon = start_lon
        self.mission_waypoints: List[Dict[str, float]] = []
        from web.mission_record import default_record

        self.mission_record: Dict[str, Any] = default_record()
        self.control_mode = "autonomous"
        self.sprayer_active = False
        self._controller = None
        self._lock = threading.Lock()
        from web.mission_runner import MissionRunner

        self.mission_runner = MissionRunner(self)

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
            "waypoint_count": len(self.mission_waypoints),
            "sprayer_active": self.sprayer_active,
        }
