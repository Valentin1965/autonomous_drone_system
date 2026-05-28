"""In-process MAVLink motion for CV (no HTTP loopback)."""


class MotionBridge:
    def _vehicle(self):
        from web.fleet import get_fleet
        from web.tracker_service import tracker_vehicle_id

        fleet = get_fleet()
        vid = tracker_vehicle_id() or fleet.selected_id
        return fleet.get_vehicle(vid)

    def move(self, forward: float, lateral: float, yaw: float = 0.0) -> bool:
        from web.fleet import get_fleet

        fleet = get_fleet()
        if fleet.emergency_stop:
            return False
        try:
            from web.tracker_service import hazard_blocks_motion

            if hazard_blocks_motion(self._vehicle().id):
                self.stop()
                return False
        except Exception:
            pass
        try:
            from web import geofence

            v = self._vehicle()
            st = v.get_controller().get_status()
            gps = st.get("gps") or {}
            try:
                from simulator import fleet_registry

                sim_gps = fleet_registry.get_position(v.id)
                if sim_gps:
                    gps = sim_gps
            except Exception:
                pass
            if geofence.is_enabled() and gps.get("lat") is not None:
                ok, msg = geofence.check_position(
                    float(gps["lat"]), float(gps["lon"])
                )
                if not ok:
                    print(f"[CV] {msg}")
                    self.stop()
                    return False
        except Exception:
            pass
        try:
            v = self._vehicle()
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
        try:
            v = self._vehicle()
            if v.mission_runner.active:
                return True
            v.get_controller().stop()
            return True
        except Exception:
            return False

    def set_sprayer(self, on: bool) -> None:
        from web.fleet import get_fleet
        from web.state import drone_state

        fleet = get_fleet()
        v = fleet.selected
        if not v:
            return
        prev = bool(v.sprayer_active)
        on_b = bool(on)
        v.sprayer_active = on_b
        drone_state.sprayer_active = on_b
        if prev != on_b:
            try:
                from monitoring.spray_coverage import on_sprayer_transition

                on_sprayer_transition(v, on_b, source="cv", uplink=True)
            except Exception:
                pass


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
