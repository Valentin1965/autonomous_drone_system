"""In-process simulator position for --full stack (Flask + sim same process)."""

_sim = None


def register(sim) -> None:
    global _sim
    _sim = sim


def get_position():
    if _sim is None:
        return None
    return _sim.get_position()
