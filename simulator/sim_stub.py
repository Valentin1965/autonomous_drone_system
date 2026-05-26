"""Швидкий in-process симулятор для pytest (без UDP)."""

from __future__ import annotations

import math
import threading
import time


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


class SimStub:
    """Мінімальний rover для тестів API / mission_runner."""

    def __init__(self, lat: float = 50.4501, lon: float = 30.5234):
        self.lat = float(lat)
        self.lon = float(lon)
        self.heading = 90.0
        self.speed = 0.0
        self.target_speed = 1.0
        self.target_heading = self.heading
        self.target_lat = None
        self.target_lon = None
        self.guided_active = False
        self.armed = False
        self.mode = "GUIDED"
        self.battery_remaining = 95.0
        self.lock = threading.Lock()
        self._last_tick = time.monotonic()
        self.step_m = 10.0

    def _tick(self) -> None:
        self._last_tick = time.monotonic()
        with self.lock:
            if not self.guided_active or self.target_lat is None:
                return
            dist = _haversine_m(self.lat, self.lon, self.target_lat, self.target_lon)
            if dist <= 2.5:
                self.lat = self.target_lat
                self.lon = self.target_lon
                self.speed = 0.0
                self.guided_active = False
                self.target_lat = None
                self.target_lon = None
                return
            step = min(self.step_m, dist * 0.9)
            fraction = step / dist
            self.lat += (self.target_lat - self.lat) * fraction
            self.lon += (self.target_lon - self.lon) * fraction
            self.speed = self.target_speed
            self.battery_remaining = max(0.0, self.battery_remaining - 0.02)

    def get_position(self) -> dict:
        self._tick()
        with self.lock:
            return {
                "lat": self.lat,
                "lon": self.lon,
                "heading": self.heading,
                "speed": self.speed,
                "battery_pct": round(self.battery_remaining, 1),
            }
