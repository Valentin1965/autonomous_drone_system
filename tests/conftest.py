"""Shared pytest fixtures — reset singletons between tests."""

import pytest


@pytest.fixture(autouse=True)
def reset_app_state():
    from web import state as web_state
    from web import tracker_service

    web_state.drone_state._controller = None
    web_state.drone_state._cfg = None
    web_state.drone_state.sprayer_active = False
    web_state.drone_state.emergency_stop = False
    tracker_service._tracker = None
    yield
