"""Application metadata for health / diagnostics."""

import time

APP_VERSION = "0.2.0-variant2"
STARTED_AT = time.time()


def uptime_s() -> float:
    return max(0.0, time.time() - STARTED_AT)
