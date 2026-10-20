"""
The window's first paint pays for every module imported before it, so
the libraries only a file import, an export or a haptic tap needs are
imported by that, not by the UI's modules (docs/PERF_AUDIT_M1.md).
"""

import subprocess
import sys

#: Imported by opening or exporting a DXF, a PDF, or by a haptic tap.
NOT_BEFORE_FIRST_PAINT = ("ezdxf", "pypdf", "AppKit", "Foundation")

_PROBE = """
import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
import swiftcut.ui_gtk.mainwindow  # noqa: F401

print(" ".join(sorted(sys.modules)))
"""


def test_the_first_paint_ui_imports_none_of_them():
    # A fresh interpreter: this one has imported half the app already.
    loaded = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert [name for name in NOT_BEFORE_FIRST_PAINT if name in loaded] == []
