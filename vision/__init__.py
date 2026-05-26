"""
DEPRECATED: use the `cv` package instead.

See vision/README.md and docs/ARCHITECTURE.md.
"""

import warnings

warnings.warn(
    "The 'vision' package is deprecated; use 'cv' (see vision/README.md).",
    DeprecationWarning,
    stacklevel=2,
)

from .detector import DummyDetector
from .navigation import CVNavigator

__all__ = ["DummyDetector", "CVNavigator"]
