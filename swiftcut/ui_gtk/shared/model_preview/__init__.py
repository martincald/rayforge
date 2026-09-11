"""
Minimal OpenGL model-preview surface shared by machine-settings pages.

This package holds the pieces of the former 3D-preview GL stack that
are NOT specific to the 3D view: the machine-settings model preview
(``ui_gtk/settings/model_preview_widget.py``) and the model-extent
lookups used by the head/rotary preferences pages.
"""

import logging
import os

# This must be checked before any GL-related imports occur.
_gl_disabled = os.environ.get("RAYFORGE_DISABLE_3D", "").lower() in (
    "true",
    "1",
)

# This flag can be checked by other parts of the application to decide
# whether OpenGL-based model preview is available.
initialized = False

# Store the exception if initialization fails, for better debugging.
initialization_error = None

logger = logging.getLogger(__name__)


def initialize():
    """
    Tries to initialize the required OpenGL bindings.

    This function attempts to import PyOpenGL. A failure indicates that
    the necessary libraries are not available on the system, and the
    OpenGL model preview cannot be used. It sets the package-level
    'initialized' flag accordingly. This should be called from the main
    application entry point before any UI is created.

    If the RAYFORGE_DISABLE_3D environment variable is set to 'true' or
    '1', the model preview is disabled without attempting initialization.
    """
    global initialized, initialization_error
    if initialized or initialization_error:
        return

    if _gl_disabled:
        logger.info(
            "OpenGL model preview disabled via RAYFORGE_DISABLE_3D "
            "environment variable."
        )
        initialized = False
        return

    try:
        # The import itself triggers platform-specific initialization and
        # will fail if the necessary libraries are not found (e.g.,
        # libGL.so).
        from OpenGL import GL  # Imported for side effects

        _ = GL  # Mark as used to silence pyflakes

        logger.info(
            "PyOpenGL imported successfully. Model preview is available."
        )
        initialized = True
    except ImportError as e:
        initialization_error = e
        logger.error(
            "Failed to import PyOpenGL. The model preview will be "
            "disabled. Error: %s",
            e,
        )
        initialized = False
    except Exception as e:
        # Catch other potential errors during initial module load.
        initialization_error = e
        logger.exception(
            "An unexpected error occurred during OpenGL initialization. "
            "The model preview will be disabled."
        )
        initialized = False


def is_available() -> bool:
    """Whether the OpenGL model preview can be used, initializing once.

    Call this instead of reading ``initialized`` directly. A
    ``from . import initialized`` binds the value at the importer's
    import time, so any caller that is imported before ``initialize()``
    runs would capture False for the life of the process. Going through
    a function also lets the PyOpenGL import stay off the startup path:
    it costs ~132 ms and nothing paints a model preview until the user
    opens machine settings.
    """
    if not initialized and initialization_error is None:
        initialize()
    return initialized
