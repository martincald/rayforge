# PyInstaller runtime hook: let cffi find libraries inside the bundle.
#
# pyvips loads libvips with ffi.dlopen("libvips.42.dylib"). A bare name
# is searched on DYLD_LIBRARY_PATH and the system paths only, never in
# the app's own Frameworks, so an app launched from Finder, with none
# of those set, cannot find it. PyInstaller already resolves bare names
# into the bundle for ctypes; this does the same for cffi.
import os
import sys

import cffi

_dlopen = cffi.FFI.dlopen


def _dlopen_in_bundle(self, name, flags=0):
    if isinstance(name, str) and os.sep not in name:
        bundled = os.path.join(sys._MEIPASS, name)
        if os.path.exists(bundled):
            name = bundled
    return _dlopen(self, name, flags)


cffi.FFI.dlopen = _dlopen_in_bundle
