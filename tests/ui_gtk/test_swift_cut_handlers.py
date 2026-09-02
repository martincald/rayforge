"""The reskin must not cost the app a signal handler.

Swift Cut is a surface change: every panel, control and handler stays
where and what it is. A reskin that quietly drops a `connect()` would
leave a button that still looks right and no longer does anything,
which no screenshot review would catch.

The counts below are the baseline at the commit that introduced the
theme. They may grow - a later feature is free to add handlers - but
they must never shrink.
"""

from importlib.resources import files

import pytest

# (package, module, the number of `.connect(` calls that must survive)
CASES = [
    ("rayforge.ui_gtk.machine", "jog_widget.py", 20),
    ("rayforge.ui_gtk.machine", "cut_scale_dialog.py", 1),
    ("rayforge.ui_gtk.doceditor", "bottom_panel.py", 28),
    ("rayforge.ui_gtk", "toolbar.py", 5),
]


@pytest.mark.parametrize("package, filename, minimum", CASES)
def test_no_handler_connections_were_removed(package, filename, minimum):
    text = files(package).joinpath(filename).read_text(encoding="utf-8")
    found = text.count(".connect(")
    assert found >= minimum, (
        f"{package}.{filename} has {found} connect() calls, down from "
        f"{minimum}. The reskin may not remove a signal handler."
    )
