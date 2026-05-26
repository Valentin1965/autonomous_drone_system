"""In-process MAVLink motion for CV (no HTTP loopback)."""


class MotionBridge:
    def move(self, forward: float, lateral: float, yaw: float = 0.0) -> bool:
        from web.fleet import get_fleet

        fleet = get_fleet()
        if fleet.emergency_stop:
            return False
        try:
            v = fleet.selected
            mr = v.mission_runner
            if mr.active:
                return False
        except Exception:
            return False
        try:
            ctrl = v.get_controller()
            from simulator import fleet_registry

            if fleet_registry.get_sim(v.id) is not None:
                try:
                    ctrl.arm()
                except Exception:
                    pass
            ctrl.set_velocity(forward, lateral, yaw)
            return True
        except Exception as e:
            print(f"[CV] MotionBridge.move failed: {e}")
            return False

    def stop(self) -> bool:
        from web.fleet import get_fleet

        try:
            get_fleet().selected.get_controller().stop()
            return True
        except Exception:
            return False

    def set_sprayer(self, on: bool) -> None:
        from web.fleet import get_fleet

        get_fleet().selected.sprayer_active = bool(on)


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
