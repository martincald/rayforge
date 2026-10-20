"""
Trackpad haptics on macOS: a Force Touch tap when a drag snaps, and on
zoom-to-fit. Anywhere else, or without PyObjC, every call is a no-op.
"""

import importlib
import importlib.util
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
        self.enabled = True
        self._clock = clock
        self._last: float | None = None
        self._logged = False
        self._performer = performer
        self._patterns: dict[str, int] = {}
        self._loaded = False
        # AppKit itself is imported by the first tap: its import takes
        # about 0.1 s, too long to pay before the window is up.
        self.available = sys.platform == "darwin" and _appkit_present()

    def _load(self) -> bool:
        """Imports AppKit once; False if it cannot be."""
        if self._loaded:
            return self.available
        self._loaded = True
        try:
            # PyObjC names are generated at runtime; as a module value
            # they type-check as Any.
            appkit = importlib.import_module("AppKit")
        except ImportError:
            self.available = False
            return False
        if self._performer is None:
            manager = appkit.NSHapticFeedbackManager
            self._performer = manager.defaultPerformer()
        self._patterns = {
            "alignment": appkit.NSHapticFeedbackPatternAlignment,
            "generic": appkit.NSHapticFeedbackPatternGeneric,
        }
        self._now = appkit.NSHapticFeedbackPerformanceTimeNow
        return True

    def perform(self, pattern: str) -> None:
        """Plays "alignment" or "generic", if it may play now."""
        if not (self.available and self.enabled and self._load()):
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


def _appkit_present() -> bool:
    """Whether AppKit can be imported, without importing it."""
    try:
        return importlib.util.find_spec("AppKit") is not None
    except ValueError:
        # Already imported, with no spec: present.
        return True


haptics = Haptics()
