"""
The window's first paint pays for every module imported before it, so
the libraries only a file import, an export or a haptic tap needs are
imported by that, not by the UI's modules (docs/PERF_AUDIT_M1.md).
"""

import subprocess
import sys

from swiftcut.shared.util.lazy_import import STARTUP_DEFERRED

#: Imported by opening or exporting a DXF, a PDF, or by a haptic tap.
NOT_BEFORE_FIRST_PAINT = ("ezdxf", "pypdf", "AppKit", "Foundation")

_PROBE = """
import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from swiftcut.shared.util.lazy_import import defer_startup_imports, is_deferred

defer_startup_imports()  # as swiftcut.app.main() does, first
import swiftcut.ui_gtk.mainwindow  # noqa: F401

print(" ".join(name for name in sorted(sys.modules) if not is_deferred(name)))
"""


def _loaded_by_the_first_paint_ui() -> list[str]:
    # A fresh interpreter: this one has imported half the app already.
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


def test_the_first_paint_ui_imports_none_of_them():
    loaded = _loaded_by_the_first_paint_ui()

    assert [name for name in NOT_BEFORE_FIRST_PAINT if name in loaded] == []


def test_the_deferred_libraries_have_not_run():
    loaded = _loaded_by_the_first_paint_ui()

    assert [name for name in STARTUP_DEFERRED if name in loaded] == []
