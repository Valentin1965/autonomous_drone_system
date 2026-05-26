"""In-process MAVLink motion for CV (no HTTP loopback)."""


class MotionBridge:
    def move(self, forward: float, lateral: float, yaw: float = 0.0) -> bool:
        from web.state import drone_state

        if drone_state.emergency_stop:
            return False
        try:
            drone_state.get_controller().set_velocity(forward, lateral, yaw)
            return True
        except Exception:
            return False

    def stop(self) -> bool:
        from web.state import drone_state

        try:
            drone_state.get_controller().stop()
            return True
        except Exception:
            return False

    def set_sprayer(self, on: bool) -> None:
        from web.state import drone_state

        drone_state.sprayer_active = bool(on)


class PrintMotion:
    """Standalone CV without Flask — logs commands only."""

    def move(self, forward: float, lateral: float, yaw: float = 0.0) -> bool:
        print(f"[CV] move forward={forward:.2f} lateral={lateral:.2f}")
        return True

    def stop(self) -> bool:
        print("[CV] stop")
        return True

    def set_sprayer(self, on: bool) -> None:
        print(f"[CV] sprayer={'on' if on else 'off'}")
