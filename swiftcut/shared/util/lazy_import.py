"""
Deferring heavy libraries the main window does not need to paint.

The image importers and renderers import pyvips, OpenCV, vtracer and
PyMuPDF at their top, and the importer registry imports every one of
them, so before the window existed the app paid for libraries that
only an image or a PDF uses. Each is imported as a plain `import name`
and used as `name.attribute`, so a placeholder in sys.modules defers
it everywhere at once: `import name` binds the placeholder, and its
first missing attribute imports the real module, whose namespace the
placeholder then takes over.

importlib.util.LazyLoader cannot do this on Python 3.14: the import
statement reads `__spec__` of a module found in sys.modules, and any
attribute read loads a LazyLoader module.
"""

import importlib
import importlib.util
import sys
import threading
import types
import warnings

#: Libraries the first paint does not use, each imported only as
#: `import name` and used as `name.attribute`.
STARTUP_DEFERRED = ("pyvips", "cv2", "vtracer", "pymupdf")


class _Deferred(types.ModuleType):
    """Stands in for a module until an attribute of it is read."""

    def __init__(self, spec):
        super().__init__(spec.name)
        self.__spec__ = spec
        # Reentrant: the real import may read the module it is importing.
        self._deferred_lock = threading.RLock()

    def __getattr__(self, attr):
        # Only reached for attributes the placeholder lacks: once the
        # real module's namespace is copied in, reads go straight to it.
        with self._deferred_lock:
            name = self.__spec__.name
            if sys.modules.get(name) is self:
                del sys.modules[name]
                try:
                    with warnings.catch_warnings():
                        # As the modules importing pyvips do around it.
                        warnings.simplefilter("ignore", DeprecationWarning)
                        module = importlib.import_module(name)
                except BaseException:
                    sys.modules[name] = self
                    raise
                self.__dict__.update(module.__dict__)
            else:
                module = sys.modules[name]
        return getattr(module, attr)


def defer(name: str) -> None:
    """
    Makes `import name` bind a placeholder that imports the module on
    its first attribute read. Does nothing if the module is imported
    already or cannot be found.
    """
    if name in sys.modules:
        return
    spec = importlib.util.find_spec(name)
    if spec is None:
        return
    sys.modules[name] = _Deferred(spec)


def is_deferred(name: str) -> bool:
    """True while `name` is a placeholder that has not imported yet."""
    module = sys.modules.get(name)
    return isinstance(module, _Deferred) and "__file__" not in vars(module)


def defer_startup_imports() -> None:
    """Defers every STARTUP_DEFERRED library; the app calls it first."""
    for name in STARTUP_DEFERRED:
        defer(name)
