"""uiscript: get the app to its idle state, then stamp it.

Opens $PERF_SCENE, if set, waits for the editor to settle and, when
$PERF_WAIT_CONNECTED is set, for the active machine to report
CONNECTED (the simulator), and minimizes the window when
$PERF_MINIMIZE is set. Then writes the stamp $PERF_OUT and returns
without quitting: measure.py samples the process from outside, idle,
and terminates it. Nothing of this script runs during the idle window.
"""

import mimetypes
import os
import time
from pathlib import Path

import uiperf
from uiperf import on_main, win

from swiftcut.context import get_context


def main():
    scene = os.environ.get("PERF_SCENE")
    if scene:
        path = Path(scene)
        if path.suffix == ".ryp":
            on_main(win.load_project, path)
        else:
            on_main(
                win.doc_editor.file.load_file_from_path,
                path,
                mimetypes.guess_type(path)[0],
                None,
            )
    uiperf.settle(extra_s=2.0)

    connected = None
    if os.environ.get("PERF_WAIT_CONNECTED"):
        deadline = time.monotonic() + 60.0
        machine = get_context().machine
        assert machine is not None
        while not on_main(machine.is_connected):
            if time.monotonic() > deadline:
                raise TimeoutError("the machine never connected")
            time.sleep(0.2)
        connected = machine.name
        uiperf.settle(extra_s=2.0)

    if os.environ.get("PERF_MINIMIZE"):
        on_main(win.minimize)
        time.sleep(1.0)

    uiperf.write_result({"ready": time.time(), "connected": connected})


uiperf.run(main, quit_after=False)
