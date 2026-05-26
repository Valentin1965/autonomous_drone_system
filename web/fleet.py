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
        from web.fleet_config import merge_fleet_config

        fleet_cfg = merge_fleet_config(cfg)
        entries = fleet_cfg.get("vehicles") or []
        if fleet_cfg.get("enabled") and len(entries) > 0:
            self.multi = len(entries) > 1 or bool(fleet_cfg.get("enabled"))
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
                    start_lat=float(v.get("start_lat", 50.4501 + i * 0.0004)),
                    start_lon=float(v.get("start_lon", 30.5234 + i * 0.0004)),
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
            )
            default = (
                fleet_cfg.get("default_vehicle")
                or fleet_cfg.get("default")
                or default_vid
            )
        if default not in self.vehicles:
            default = next(iter(self.vehicles))
        self.selected_id = default
        try:
            from simulator import fleet_registry

            fleet_registry.set_active(self.selected_id)
        except Exception:
            pass

    @property
    def selected(self) -> Vehicle:
        self.load_config()
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
        with self._lock:
            self.selected_id = v.id
        try:
            from simulator import fleet_registry

            if fleet_registry.get_sim(v.id):
                fleet_registry.set_active(v.id)
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

        return {
            "multi": self.multi,
            "count": len(self.vehicles),
            "min_count": MIN_FLEET,
            "max_count": MAX_FLEET,
            "selected_vehicle_id": self.selected_id,
            "vehicles": self.list_status(),
        }

    def configure_fleet_count(self, count: int) -> dict:
        """Змінити кількість дронів; зберегти в config/fleet_runtime.yaml."""
        from web.fleet_config import (
            MAX_FLEET,
            MIN_FLEET,
            build_vehicle_entries,
            save_runtime_fleet,
        )

        cfg = self.load_config()
        n = max(MIN_FLEET, min(MAX_FLEET, int(count)))
        entries = build_vehicle_entries(n, cfg)
        existing = dict(self.vehicles)
        new_map: Dict[str, Vehicle] = {}
        for i, ent in enumerate(entries):
            vid = str(ent["id"])
            if vid in existing:
                v = existing[vid]
                if v.mavlink_connection != ent["mavlink_connection"]:
                    v.reset_controller()
                v.mavlink_connection = ent["mavlink_connection"]
                v.sim_bind = ent.get("sim_bind")
                v.start_lat = float(ent.get("start_lat", v.start_lat))
                v.start_lon = float(ent.get("start_lon", v.start_lon))
                new_map[vid] = v
            else:
                new_map[vid] = Vehicle(
                    vehicle_id=vid,
                    name=str(ent.get("name") or vid),
                    mavlink_connection=ent["mavlink_connection"],
                    color=str(ent.get("color") or _COLORS[i % len(_COLORS)]),
                    sim_bind=ent.get("sim_bind"),
                    start_lat=float(ent.get("start_lat", 50.4501)),
                    start_lon=float(ent.get("start_lon", 30.5234)),
                )
        self.vehicles = new_map
        self.multi = n > 1
        if self.selected_id not in self.vehicles:
            self.selected_id = entries[0]["id"]
        save_runtime_fleet(n, entries, self.selected_id or "rover_1")
        cfg.setdefault("fleet", {})
        cfg["fleet"]["enabled"] = True
        cfg["fleet"]["vehicles"] = entries
        cfg["fleet"]["default_vehicle"] = self.selected_id
        sim_ok = self._sync_simulators_for_fleet()
        self.warmup_connections()
        logger.info("Fleet reconfigured: %d vehicles", n)
        msg = f"Флот: {n} дрон(и). Селектор оновлено."
        if not sim_ok:
            msg += " Після зміни кількості дронів — перезапусти станцію."
        return {
            **self.fleet_payload(),
            "requires_restart": not sim_ok,
            "simulators_synced": sim_ok,
            "message": msg,
        }

    def _sync_simulators_for_fleet(self) -> bool:
        """Підняти симулятори для нових vehicle без повного рестарту main."""
        import threading

        from simulator import fleet_registry
        from simulator.pixhawk_simulator import PixhawkGPSSimulator

        all_ok = True
        for i, (vid, vehicle) in enumerate(self.vehicles.items()):
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
        if self.selected_id:
            try:
                fleet_registry.set_active(self.selected_id)
            except KeyError:
                all_ok = False
        for vid in self.vehicles:
            if fleet_registry.get_sim(vid) is None:
                all_ok = False
        return all_ok

    def warmup_connections(self) -> dict:
        """Підключити MAVLink для кожного дрона (після старту симуляторів)."""
        results = {}
        for vid, vehicle in self.vehicles.items():
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
