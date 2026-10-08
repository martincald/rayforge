"""
The macOS startup splash: a borderless window with the SwiftCut splash
image, shown by a small child process while the app imports GTK.

swiftcut.app.main() spawns the child first thing, before `import gi`,
and closes it when the main window is mapped. The child imports only
the standard library and PyObjC's core, so it is on screen long before
the app is. It never takes focus and has no Dock tile, it exits when its
stdin closes (the app exited or crashed) and after MAX_SECONDS at the
latest, and any failure on either side only means there is no splash.

From source the child is `python -m swiftcut.splash IMAGE`. In the
bundle sys.executable is the app's own launcher, so the child is that
launcher with FROZEN_FLAG. There scripts/mac/pyi_rth_splash.py, the
bundle's first Python, spawns the child even earlier than main() (which
then finds it up and spawns none), and routes the child itself to run()
before the app's own startup code.
"""

import importlib
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

FROZEN_FLAG = "--swiftcut-splash"
# A file to stamp with time.time() once the window is up, for timing.
MARK_ENV = "PERF_SPLASH_MARK_FILE"
MAX_SECONDS = 60

APPKIT = "/System/Library/Frameworks/AppKit.framework/AppKit"
# AppKit's own values for the constants run() needs.
ACTIVATION_POLICY_ACCESSORY = 1  # no Dock tile, never the active app
WINDOW_STYLE_BORDERLESS = 0
BACKING_STORE_BUFFERED = 2
FLOATING_WINDOW_LEVEL = 3

# Held for the life of the splash: dropping it closes the child's stdin,
# which ends the child.
_proc: subprocess.Popen | None = None


def spawn(image: Path) -> None:
    """Starts the splash child, on macOS, if the image exists."""
    global _proc
    if sys.platform != "darwin" or _proc is not None:
        return
    if not image.is_file():
        return
    if hasattr(sys, "_MEIPASS"):
        argv = [sys.executable, FROZEN_FLAG, str(image)]
    else:
        argv = [sys.executable, "-m", "swiftcut.splash", str(image)]
    try:
        _proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        logger.debug("Splash not shown", exc_info=True)


def close() -> None:
    """Takes the splash down. Safe to call any number of times."""
    global _proc
    proc, _proc = _proc, None
    if proc is None:
        return
    try:
        # EOF ends the child too, even if the signal does not.
        if proc.stdin is not None:
            proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=1)
    except Exception:
        logger.debug("Splash close failed", exc_info=True)


def _exit_on_eof() -> None:
    try:
        while os.read(0, 1024):
            pass
    finally:
        # Also when stdin is unreadable: a splash that cannot see the
        # app go away must not outlive it.
        os._exit(0)


def run(argv: list[str]) -> int:
    """The child: shows the image centred until terminated."""
    if not argv or not Path(argv[0]).is_file():
        return 1
    threading.Thread(target=_exit_on_eof, daemon=True).start()
    cap = threading.Timer(MAX_SECONDS, os._exit, args=(0,))
    cap.daemon = True
    cap.start()

    # The few AppKit classes needed, looked up in the runtime: PyObjC's
    # AppKit wrapper would take about twice as long to import. ctypes
    # is imported here so that the parent never loads it.
    import ctypes

    ctypes.cdll.LoadLibrary(APPKIT)
    # PyObjC names are generated at runtime; as a module value they
    # type-check as Any.
    objc = importlib.import_module("objc")
    cls = objc.lookUpClass
    app = cls("NSApplication").sharedApplication()
    app.setActivationPolicy_(ACTIVATION_POLICY_ACCESSORY)
    image = cls("NSImage").alloc().initWithContentsOfFile_(argv[0])
    if image is None:
        return 1
    window = cls("NSWindow").alloc()
    window = window.initWithContentRect_styleMask_backing_defer_(
        ((0, 0), image.size()),
        WINDOW_STYLE_BORDERLESS,
        BACKING_STORE_BUFFERED,
        False,
    )
    window.setOpaque_(False)
    window.setBackgroundColor_(cls("NSColor").clearColor())
    window.setHasShadow_(True)
    window.setLevel_(FLOATING_WINDOW_LEVEL)
    window.setContentView_(cls("NSImageView").imageViewWithImage_(image))
    window.center()
    window.display()
    window.orderFrontRegardless()

    mark = os.environ.get(MARK_ENV)
    if mark:
        Path(mark).write_text(repr(time.time()), encoding="utf-8")
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
