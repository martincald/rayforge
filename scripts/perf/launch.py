"""Runs swiftcut.app for a measurement, beside any other SwiftCut.

Identical to ``python -m swiftcut.app ARGS`` except that the
single-instance guard listens on $PERF_GUARD_PORT instead of 51987. An
instance started by the owner while a measurement runs then starts
normally, instead of finding the measured instance, asking it to come
to the front and exiting.
"""

import os
import sys

if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    from swiftcut import single_instance

    port = int(os.environ.get("PERF_GUARD_PORT", "51999"))
    single_instance.SingleInstanceGuard.__init__.__defaults__ = (port,)

    from swiftcut.app import main

    sys.exit(main())
