"""After a switch from ilab-614 (1400 x 900 mm) to ilab-626 (900 x 900
mm) the canvas shows, and keeps drags on, the active machine's bed.
MainWindow.on_config_changed hands the surface config.machine through
set_machine; this does the same."""

import copy

import pytest
from gi.repository import Gtk

from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.default_profile import (
    ILAB_614_PROFILE,
    ILAB_626_PROFILE,
)
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

pytestmark = pytest.mark.ui


def _bundled(profile, context):
    """A bundled profile that never dials out."""
    data = copy.deepcopy(profile)
    data["machine"]["driver_args"]["connection"] = "udp"
    data["machine"]["driver_args"]["host"] = "192.0.2.1"
    data["machine"]["auto_connect"] = False
    return Machine.from_dict(data, context=context)


def test_the_canvas_bed_follows_a_machine_switch(
    ui_context_initializer, ui_task_mgr
):
    ilab_614 = _bundled(ILAB_614_PROFILE, ui_context_initializer)
    ilab_626 = _bundled(ILAB_626_PROFILE, ui_context_initializer)
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    window = Gtk.Window()
    try:
        surface = WorkSurface(editor, window, ilab_614)
        assert (surface.width_mm, surface.height_mm) == (1400.0, 900.0)

        surface.set_machine(ilab_626)

        assert (surface.width_mm, surface.height_mm) == (900.0, 900.0)
        assert surface._tracked_axis_extents == (900.0, 900.0)
        frame = surface._extent_frame_element
        assert (frame.width, frame.height) == (900.0, 900.0)
        assert surface._drag_bounds() == (0.0, 0.0, 900.0, 900.0)

        # A later change to the old machine no longer reaches it.
        ilab_614.set_axis_extents(1500.0, 900.0)
        assert (surface.width_mm, surface.height_mm) == (900.0, 900.0)
    finally:
        editor.cleanup()
        window.destroy()
