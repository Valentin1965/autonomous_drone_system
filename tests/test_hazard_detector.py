"""YOLO hazard ROI logic (без інференсу)."""

import numpy as np

from cv.hazard_detector import HazardDetector, HazardHit


def test_hazard_stop_when_person_in_roi():
    det = HazardDetector(
        {
            "enabled": True,
            "stop_area_ratio": 0.03,
            "min_box_area_ratio": 0.001,
            "classes": ["person"],
            "roi": {"x_margin": 0.1, "y_start": 0.1},
        }
    )
    det._model = object()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    class FakeBoxes:
        xyxy = [np.array([200.0, 300.0, 400.0, 450.0])]
        cls = [np.array(0)]
        conf = [np.array(0.9)]

        def __len__(self):
            return len(self.xyxy)

    class FakeResult:
        names = {0: "person"}
        boxes = FakeBoxes()

    class FakeModel:
        def __call__(self, *args, **kwargs):
            return [FakeResult()]

    det._model = FakeModel()

    res = det.analyze(frame)
    assert res.stop
    assert any(h.class_name == "person" for h in res.hits)


def test_hazard_ignores_class_outside_list():
    det = HazardDetector(
        {
            "enabled": True,
            "stop_area_ratio": 0.01,
            "classes": ["person"],
            "roi": {"x_margin": 0.0, "y_start": 0.0},
        }
    )

    class FakeBoxes:
        xyxy = [np.array([10.0, 10.0, 200.0, 200.0])]
        cls = [np.array(0)]
        conf = [np.array(0.95)]

        def __len__(self):
            return len(self.xyxy)

    class FakeResult:
        names = {0: "banana"}
        boxes = FakeBoxes()

    class FakeModel:
        def __call__(self, *args, **kwargs):
            return [FakeResult()]

    det._model = FakeModel()
    res = det.analyze(np.zeros((480, 640, 3), dtype=np.uint8))
    assert not res.stop
    assert len(res.hits) == 0
