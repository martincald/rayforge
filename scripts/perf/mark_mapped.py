"""uiscript that stamps the moment the main window is mapped, then quits.

Used by ``scripts/perf/measure.py`` to time cold start without editing
the application. ``--uiscript`` is itself run from a ``map`` handler
(``app.py:351``), so by the time this module executes the window is on
screen and ``_close_splash`` has already run - which makes "now" the
same instant the user first sees the app.

The stamp is written to the file named by ``$PERF_MARK_FILE`` so the
parent process can read it without parsing the log.
"""

import os
import time
from pathlib import Path

from swiftcut.uiscript import app

_mark = os.environ.get("PERF_MARK_FILE")
if _mark:
    Path(_mark).write_text(repr(time.time()), encoding="utf-8")

app.quit_idle()
