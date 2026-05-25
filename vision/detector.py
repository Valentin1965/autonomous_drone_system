import numpy as np


class DummyDetector:
    """
    Заглушка детектора.
    Повертає порожній список — можна замінити на YOLO, OpenCV, TensorRT тощо.
    """

    def detect(self, frame) -> list:
        """
        Повертає список знайдених об'єктів.
        Формат елемента списку:
        {
            "x": float,
            "y": float,
            "confidence": float
        }
        """
        return []
