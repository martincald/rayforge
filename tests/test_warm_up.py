"""swiftcut.warm_up: what the first paint defers is loaded afterwards."""

import subprocess
import sys

_PROBE = """
import sys
from swiftcut.shared.util.lazy_import import (
    STARTUP_DEFERRED, defer_startup_imports, is_deferred,
)
defer_startup_imports()  # as swiftcut.app.main() does
from swiftcut.warm_up import FILE_FORMAT_LIBRARIES, warm_up
warm_up()
names = STARTUP_DEFERRED + FILE_FORMAT_LIBRARIES
print(" ".join(n for n in names if n not in sys.modules or is_deferred(n)))
"""


def test_warm_up_loads_every_deferred_library():
    # A fresh interpreter: in this one they are loaded already.
    not_loaded = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert not_loaded == []


def test_a_failing_warm_up_is_only_logged(monkeypatch):
    from swiftcut import warm_up

    def fail():
        raise ImportError("no such library")

    monkeypatch.setattr(warm_up, "warm_up", fail)

    warm_up._run()  # must not raise
