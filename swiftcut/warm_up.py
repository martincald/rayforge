"""
Loading, once the window is up, what startup leaves for later.

The first paint does without the image and file-format libraries
(docs/PERF_AUDIT_M1.md), but the first file a user opens needs them.
The app loads them off the main thread a moment after the window maps,
so neither the first paint nor the first file pays for them.
"""

import importlib
import logging
import threading

logger = logging.getLogger(__name__)

#: Imported where a DXF or a PDF is read, not at their modules' top.
FILE_FORMAT_LIBRARIES = ("ezdxf", "pypdf")


def warm_up() -> None:
    """Loads everything startup deferred, now, on this thread."""
    from .image.svg.svg_fallback import svg_load_available
    from .shared.util.lazy_import import STARTUP_DEFERRED, load

    for name in STARTUP_DEFERRED:
        load(name)
    for name in FILE_FORMAT_LIBRARIES:
        importlib.import_module(name)
    svg_load_available()


def warm_up_in_background() -> None:
    """warm_up() on a daemon thread; a failure is logged, never raised."""
    threading.Thread(target=_run, name="warm-up", daemon=True).start()


def _run() -> None:
    try:
        warm_up()
    except Exception:
        # Only ever a slower first use: the file read imports them.
        logger.debug("Warm-up failed", exc_info=True)
