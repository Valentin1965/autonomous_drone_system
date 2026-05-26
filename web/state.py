"""Фасад до обраного дрона у флоті (зворотна сумісність API)."""

import threading

from utils.logger import setup_logger

logger = setup_logger("drone_web_panel")


class DroneState:
    """Делегує до get_fleet().selected."""

    def _fleet(self):
        from web.fleet import get_fleet

        return get_fleet()

    def _vehicle(self):
        return self._fleet().selected

    @property
    def sprayer_active(self) -> bool:
        return self._vehicle().sprayer_active

    @sprayer_active.setter
    def sprayer_active(self, value: bool) -> None:
        self._vehicle().sprayer_active = bool(value)

    @property
    def emergency_stop(self) -> bool:
        return self._fleet().emergency_stop

    @emergency_stop.setter
    def emergency_stop(self, value: bool) -> None:
        self._fleet().emergency_stop = bool(value)

    @property
    def mission_waypoints(self):
        return self._vehicle().mission_waypoints

    @mission_waypoints.setter
    def mission_waypoints(self, value) -> None:
        self._vehicle().mission_waypoints = value

    def get_control_mode(self) -> str:
        return self._vehicle().get_control_mode()

    def set_control_mode(self, mode: str) -> None:
        self._vehicle().set_control_mode(mode)

    def load_config(self) -> dict:
        return self._fleet().load_config()

    def get_controller(self):
        return self._vehicle().get_controller()


drone_state = DroneState()
