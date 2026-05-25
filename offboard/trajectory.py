import math


def square_trajectory(size=5.0, alt=-3.0):
    """
    Generates a simple square trajectory in LOCAL_NED.
    """
    return [
        (0.0, 0.0, alt),
        (size, 0.0, alt),
        (size, size, alt),
        (0.0, size, alt),
    ]


def circle_trajectory(radius=5.0, alt=-3.0, points=36):
    """
    Generates a circular trajectory in LOCAL_NED.
    """
    result = []
    for i in range(points):
        angle = 2 * math.pi * (i / points)
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        result.append((x, y, alt))
    return result


def line_trajectory(length=10.0, alt=-3.0, steps=20):
    """
    Generates a straight line trajectory.
    """
    return [(length * (i / steps), 0.0, alt) for i in range(steps + 1)]
