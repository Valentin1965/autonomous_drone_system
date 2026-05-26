"""CV tracker uses in-process motion, not HTTP."""

import pytest

pytest.importorskip("ultralytics")

from cv.tracker import YOLOSegmentationTracker


class FakeMotion:
    def __init__(self):
        self.calls = []

    def move(self, forward, lateral, yaw=0.0):
        self.calls.append(("move", forward, lateral))
        return True

    def stop(self):
        self.calls.append(("stop",))
        return True

    def set_sprayer(self, on):
        self.calls.append(("sprayer", on))


@pytest.mark.slow
def test_tracker_uses_motion_not_requests():
    motion = FakeMotion()
    t = YOLOSegmentationTracker(
        config={"yolo_device": "cpu"},
        motion=motion,
        source="synthetic",
    )
    t._do_move(0.5, 0.1)
    t._do_stop()
    assert ("move", 0.5, 0.1) in motion.calls
    assert ("stop",) in motion.calls
