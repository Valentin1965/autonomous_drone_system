"""Флот однотипних rover — окремі маршрути, ручний режим лише для обраного."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from utils.logger import setup_logger
from web.vehicle import Vehicle

logger = setup_logger("drone_fleet")

_COLORS = ("#ff9800", "#4caf50", "#2196f3", "#e91e63", "#9c27b0", "#00bcd4")


def _fleet_default_lat(index: int) -> float:
    from web.fleet_config import _default_lat

    return _default_lat(index)


def _fleet_default_lon(index: int) -> float:
    from web.fleet_config import _default_lon

    return _default_lon(index)


class FleetManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cfg: Optional[dict] = None
        self.vehicles: Dict[str, Vehicle] = {}
        self.selected_id: Optional[str] = None
        self.emergency_stop = False
        self.multi = False

    def load_config(self) -> dict:
        if self._cfg is None:
            from config.config_paths import system_config_path

            with open(system_config_path(), "r", encoding="utf-8") as f:
                self._cfg = yaml.safe_load(f) or {}
            self._ensure_vehicles()
        return self._cfg

    def _ensure_vehicles(self) -> None:
        if self.vehicles:
            return
        cfg = self._cfg or {}
        from web.fleet_config import (
            default_fleet_video_file,
            merge_fleet_config,
            resolve_active_ids,
        )

        fleet_cfg = merge_fleet_config(cfg)
        entries = fleet_cfg.get("vehicles") or []
        active_ids = set(resolve_active_ids(fleet_cfg, entries))
        if fleet_cfg.get("enabled") and len(entries) > 0:
            self.multi = len(entries) > 1
            for i, v in enumerate(entries):
                vid = str(v.get("id") or f"rover_{i + 1}")
                conn = (
                    v.get("mavlink_connection")
                    or v.get("connection")
                    or cfg.get("mavlink", {}).get("connection_sim")
                    or "udp:127.0.0.1:14550"
                )
                self.vehicles[vid] = Vehicle(
                    vehicle_id=vid,
                    name=str(v.get("name") or vid),
                    mavlink_connection=conn,
                    color=str(v.get("color") or _COLORS[i % len(_COLORS)]),
                    sim_bind=v.get("sim_bind"),
                    start_lat=float(
                        v.get("start_lat", _fleet_default_lat(i))
                    ),
                    start_lon=float(
                        v.get("start_lon", _fleet_default_lon(i))
                    ),
                    video_file=v.get("video_file") or default_fleet_video_file(i),
                    active=vid in active_ids,
                )
            default = (
                fleet_cfg.get("default_vehicle")
                or fleet_cfg.get("default")
                or next(iter(self.vehicles))
            )
        else:
            self.multi = False
            from mavlink.runtime_config import client_connection_string

            default_vid = "rover_1"
            self.vehicles[default_vid] = Vehicle(
                vehicle_id=default_vid,
                name="Rover 1",
                mavlink_connection=client_connection_string(cfg),
                color=_COLORS[0],
                sim_bind=cfg.get("simulator", {}).get("connection_string"),
                active=True,
            )
            default = (
                fleet_cfg.get("default_vehicle")
                or fleet_cfg.get("default")
                or default_vid
            )
        if default not in self.vehicles or not self.vehicles[default].active:
            default = next(
                (v.id for v in self.vehicles.values() if v.active),
                next(iter(self.vehicles)),
            )
        self.selected_id = default
        try:
            from simulator import fleet_registry

            if fleet_registry.get_sim(self.selected_id):
                fleet_registry.set_active(self.selected_id)
        except Exception:
            pass

    def active_vehicle_ids(self) -> List[str]:
        self.load_config()
        return [v.id for v in self.vehicles.values() if v.active]

    def active_vehicles(self) -> List[Vehicle]:
        self.load_config()
        return [v for v in self.vehicles.values() if v.active]

    def _pool_entries_for_runtime(self) -> List[dict]:
        from web.fleet_config import build_pool_entries

        cfg = self.load_config()
        entries = build_pool_entries(cfg)
        by_id = {str(e["id"]): e for e in entries}
        out = []
        for vid in sorted(self.vehicles.keys(), key=lambda x: int(x.rsplit("_", 1)[-1])):
            v = self.vehicles[vid]
            ent = dict(by_id.get(vid, {"id": vid}))
            ent.update({
                "id": v.id,
                "name": v.name,
                "color": v.color,
                "mavlink_connection": v.mavlink_connection,
                "sim_bind": v.sim_bind,
                "start_lat": v.start_lat,
                "start_lon": v.start_lon,
                "video_file": v.video_file,
                "active": v.active,
            })
            out.append(ent)
        return out

    def _persist_runtime(self) -> None:
        from web.fleet_config import save_runtime_fleet

        active_ids = self.active_vehicle_ids()
        save_runtime_fleet(
            self._pool_entries_for_runtime(),
            self.selected_id or "rover_1",
            active_ids,
        )

    def _apply_active_ids(self, active_ids: List[str]) -> None:
        from web.fleet_config import FLEET_POOL_SIZE, MIN_FLEET
        from simulator import fleet_registry

        pool_ids = set(self.vehicles.keys())
        chosen = [vid for vid in active_ids if vid in pool_ids]
        if len(chosen) < MIN_FLEET:
            raise ValueError(f"Потрібен щонайменше {MIN_FLEET} активний дрон")
        if len(chosen) > FLEET_POOL_SIZE:
            raise ValueError(f"Максимум {FLEET_POOL_SIZE} дронів у пулі")
        chosen_set = set(chosen)
        for vid, vehicle in self.vehicles.items():
            was_active = vehicle.active
            vehicle.active = vid in chosen_set
            if was_active and not vehicle.active:
                try:
                    if vehicle.mission_runner.active:
                        vehicle.mission_runner.stop()
                except Exception:
                    pass
                fleet_registry.unregister_vehicle(vid)
                vehicle.reset_controller()
        if self.selected_id not in chosen_set:
            self.selected_id = chosen[0]
        self.multi = len(self.vehicles) > 1
        self._persist_runtime()
        sim_ok = self._sync_simulators_for_fleet()
        self.warmup_connections()
        if self.selected_id and fleet_registry.get_sim(self.selected_id):
            try:
                fleet_registry.set_active(self.selected_id)
            except Exception:
                pass
        return sim_ok

    @property
    def selected(self) -> Vehicle:
        self.load_config()
        if not self.vehicles:
            raise KeyError("fleet has no vehicles")
        if self.selected_id not in self.vehicles:
            self.selected_id = next(iter(self.vehicles))
        return self.vehicles[self.selected_id]

    def get_vehicle(self, vehicle_id: Optional[str] = None) -> Vehicle:
        self.load_config()
        vid = vehicle_id or self.selected_id
        if vid not in self.vehicles:
            raise KeyError(f"unknown vehicle: {vid}")
        return self.vehicles[vid]

    def select(self, vehicle_id: str) -> Vehicle:
        v = self.get_vehicle(vehicle_id)
        old_id = self.selected_id
        with self._lock:
            self.selected_id = v.id
        try:
            from simulator import fleet_registry

            if fleet_registry.get_sim(v.id):
                fleet_registry.set_active(v.id)
        except Exception:
            pass
        if old_id != v.id:
            try:
                from web.tracker_service import on_fleet_vehicle_selected

                on_fleet_vehicle_selected(v.id, old_id)
            except Exception:
                pass
        logger.info("Selected vehicle: %s", v.id)
        return v

    def list_status(self) -> List[dict]:
        self.load_config()
        out = []
        for v in self.vehicles.values():
            s = v.status_summary()
            s["selected"] = v.id == self.selected_id
            out.append(s)
        return out

    def fleet_payload(self) -> dict:
        self.load_config()
        from web.fleet_config import MAX_FLEET, MIN_FLEET

        cv_mode = "local"
        try:
            from web.tracker_service import cv_mode as _cv_mode

            cv_mode = _cv_mode()
        except Exception:
            cv_mode = "local"

        return {
            "multi": self.multi,
            "pool_size": len(self.vehicles),
            "count": len(self.active_vehicle_ids()),
            "active_vehicle_ids": self.active_vehicle_ids(),
            "min_count": MIN_FLEET,
            "max_count": MAX_FLEET,
            "selected_vehicle_id": self.selected_id,
            "vehicles": [{**v, "cv_mode": cv_mode} for v in self.list_status()],
        }

    def configure_fleet_active(self, active_ids: List[str]) -> dict:
        """Оператор обирає, які дрони з пулу (6) у роботі."""
        self.load_config()
        sim_ok = self._apply_active_ids(list(active_ids))
        n = len(self.active_vehicle_ids())
        logger.info("Fleet active set: %s", self.active_vehicle_ids())
        msg = f"У роботі: {n} з {len(self.vehicles)} дронів."
        if not sim_ok:
            msg += " Для нових симуляторів — перезапусти станцію."
        return {
            **self.fleet_payload(),
            "requires_restart": not sim_ok,
            "simulators_synced": sim_ok,
            "message": msg,
        }

    def configure_fleet_count(self, count: int) -> dict:
        """Швидкий вибір: перші N дронів з пулу (rover_1 … rover_N)."""
        from web.fleet_config import active_ids_for_count

        return self.configure_fleet_active(active_ids_for_count(count))

    def set_vehicle_active(self, vehicle_id: str, active: bool) -> dict:
        """Увімкнути/вимкнути один дрон у пулі."""
        self.load_config()
        v = self.get_vehicle(vehicle_id)
        ids = self.active_vehicle_ids()
        if active:
            if v.id not in ids:
                ids.append(v.id)
        else:
            if len(ids) <= 1:
                raise ValueError("Має лишитись щонайменше один активний дрон")
            ids = [x for x in ids if x != v.id]
        return self.configure_fleet_active(ids)

    def _sync_simulators_for_fleet(self) -> bool:
        """Симулятори лише для активних дронів."""
        import threading

        from simulator import fleet_registry
        from simulator.pixhawk_simulator import PixhawkGPSSimulator

        all_ok = True
        active_ids = set(self.active_vehicle_ids())
        for vid in list(fleet_registry.list_vehicle_ids()):
            if vid not in active_ids:
                fleet_registry.unregister_vehicle(vid)
        for i, (vid, vehicle) in enumerate(sorted(self.vehicles.items())):
            if not vehicle.active:
                continue
            if fleet_registry.get_sim(vid) is not None:
                continue
            bind = vehicle.sim_bind or "udpin:0.0.0.0:14550"
            try:
                sim = PixhawkGPSSimulator(
                    bind,
                    start_lat=vehicle.start_lat,
                    start_lon=vehicle.start_lon,
                    mavlink_system_id=i + 1,
                )
                fleet_registry.register_vehicle(vid, sim)

                def _run(s=sim):
                    s.simulate_movement()

                threading.Thread(
                    target=_run, name=f"sim-{vid}", daemon=True
                ).start()
                logger.info("Simulator started for %s @ %s", vid, bind)
            except Exception as e:
                all_ok = False
                logger.warning("Simulator %s failed: %s", vid, e)
        if self.selected_id and self.selected_id in active_ids:
            try:
                if fleet_registry.get_sim(self.selected_id):
                    fleet_registry.set_active(self.selected_id)
            except KeyError:
                all_ok = False
        for vid in active_ids:
            if fleet_registry.get_sim(vid) is None:
                all_ok = False
        return all_ok

    def warmup_connections(self) -> dict:
        """MAVLink warmup — лише активні дрони."""
        results = {}
        for vid, vehicle in self.vehicles.items():
            if not vehicle.active:
                results[vid] = "inactive"
                continue
            try:
                vehicle.get_controller().ensure_connected()
                results[vid] = "ok"
            except Exception as e:
                results[vid] = str(e)
                logger.warning("MAVLink warmup [%s]: %s", vid, e)
        return results


_fleet: Optional[FleetManager] = None


def get_fleet() -> FleetManager:
    global _fleet
    if _fleet is None:
        _fleet = FleetManager()
        _fleet.load_config()
    return _fleet


def reset_fleet_singleton() -> None:
    """Скинути singleton (тести)."""
    global _fleet
    _fleet = None


def resolve_vehicle_id(request=None, data: Optional[dict] = None) -> str:
    """vehicle_id з query, JSON або обраний."""
    vid = None
    if request is not None:
        vid = request.args.get("vehicle_id") or request.args.get("vehicle")
    if not vid and data:
        vid = data.get("vehicle_id") or data.get("vehicle")
    fleet = get_fleet()
    if vid:
        fleet.get_vehicle(vid)
        return str(vid)
    return fleet.selected_id
