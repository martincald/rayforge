"""
Trackpad haptics on macOS: a Force Touch tap when a drag snaps, and on
zoom-to-fit. Anywhere else, or without PyObjC, every call is a no-op.
"""

import importlib
import logging
import sys
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class Haptics:
    """
    Plays NSHapticFeedbackManager patterns, at most one per
    MIN_INTERVAL_MS. A failing call is logged once and never raised.
    """

    MIN_INTERVAL_MS = 60

    def __init__(
        self,
        performer: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.available = False
        self.enabled = True
        self._clock = clock
        self._last: float | None = None
        self._logged = False
        self._performer = performer
        self._patterns: dict[str, int] = {}
        if sys.platform != "darwin":
            return
        try:
            # PyObjC names are generated at runtime; as a module value
            # they type-check as Any.
            appkit = importlib.import_module("AppKit")
        except ImportError:
            return
        if self._performer is None:
            manager = appkit.NSHapticFeedbackManager
            self._performer = manager.defaultPerformer()
        self._patterns = {
            "alignment": appkit.NSHapticFeedbackPatternAlignment,
            "generic": appkit.NSHapticFeedbackPatternGeneric,
        }
        self._now = appkit.NSHapticFeedbackPerformanceTimeNow
        self.available = True

    def perform(self, pattern: str) -> None:
        """Plays "alignment" or "generic", if it may play now."""
        if not (self.available and self.enabled):
            return
        now = self._clock()
        if (
            self._last is not None
            and (now - self._last) * 1000 < self.MIN_INTERVAL_MS
        ):
            return
        self._last = now
        try:
            self._performer.performFeedbackPattern_performanceTime_(
                self._patterns[pattern], self._now
            )
        except Exception:
            if not self._logged:
                self._logged = True
                logger.debug("Haptic feedback failed", exc_info=True)

    def alignment(self) -> None:
        self.perform("alignment")

    def generic(self) -> None:
        self.perform("generic")


haptics = Haptics()
