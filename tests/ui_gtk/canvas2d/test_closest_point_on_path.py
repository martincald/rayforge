"""The closest point on a workpiece's path, as the context menu's "Add
tab" uses it: found in the unit square the path lives in, whatever the
workpiece's natural size, and returned in the form the editor reads.
"""

import pytest
from gi.repository import Gtk
from raygeo.geo import Geometry

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.machine.models.machine import Machine
from swiftcut.ui_gtk.canvas2d.surface import WorkSurface

pytestmark = pytest.mark.ui


def _rectangle():
    """A closed rectangle filling the workpiece's box."""
    geo = Geometry()
    geo.move_to(0.0, 0.0)
    geo.line_to(1.0, 0.0)
    geo.line_to(1.0, 1.0)
    geo.line_to(0.0, 1.0)
    geo.close_path()
    return geo


@pytest.fixture
def surface(ui_context_initializer, ui_task_mgr):
    """A real editor and an 800x600 surface; returns them with a
    function adding a workpiece with a path."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    machine = Machine(ui_context_initializer)
    machine.set_axis_extents(200, 200)
    s = WorkSurface(editor, Gtk.Window(), machine)
    s.get_width = lambda: 800
    s.get_height = lambda: 600
    s._rebuild_view_transform()

    def add(geometry, pos, size):
        wp = WorkPiece(name="wp")
        wp._edited_boundaries = geometry
        wp.set_size(*size)
        wp.pos = pos
        editor.doc.active_layer.add_child(wp)
        s.update_from_doc()
        elem = s.find_by_data(wp)
        assert elem is not None
        return wp, elem

    yield editor, s, add

    editor.cleanup()


def test_the_closest_point_ignores_the_natural_size(surface):
    editor, _, add = surface
    wp, elem = add(_rectangle(), (10, 20), (100, 50))
    # Neither 1x1 nor the placed size: the path is still the unit square.
    wp.natural_width_mm, wp.natural_height_mm = 200, 100

    # 1 mm below the bottom edge, which runs from (10, 20) to (110, 20).
    location = elem.get_closest_point_on_path(60, 19, threshold_px=50)

    assert location is not None
    assert set(location) == {"segment_index", "pos"}
    point = wp.boundaries.get_point_at(
        location["segment_index"], location["pos"]
    )
    world_x, world_y = elem.get_world_transform().transform_point(point[:2])
    assert world_x == pytest.approx(60, abs=1e-6)
    assert world_y == pytest.approx(20, abs=1e-6)

    # What the context menu's "Add tab" does with it.
    editor.add_tab_from_context({"workpiece": wp, "location": location})
    tab = wp.tabs[-1]
    assert tab.segment_index == location["segment_index"]
    assert tab.pos == location["pos"]
