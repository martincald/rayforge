# flake8: noqa: E402
"""
The import dialog's "Import as", above the layer list: Single shape
(the default, every time) or Individual shapes, one workpiece per path,
selected once imported. Direct vector imports only.
"""

import os
import sys
import time
from pathlib import Path

import pytest

if sys.platform.startswith("linux"):
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    if not os.environ.get("DISPLAY"):
        pytest.skip(
            "DISPLAY not set on Linux, skipping UI tests. Run with xvfb-run.",
            allow_module_level=True,
        )

import ezdxf
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from swiftcut.core.source_asset import SourceAsset
from swiftcut.core.vectorization_spec import LayerImportMode, PassthroughSpec
from swiftcut.doceditor.editor import DocEditor
from swiftcut.image.dxf.importer import DxfImporter
from swiftcut.image.dxf.renderer import DXF_RENDERER
from swiftcut.image.svg.importer import SvgImporter
from swiftcut.shared.tasker import task_mgr
from swiftcut.ui_gtk.doceditor.import_dialog import ImportDialog
from swiftcut.ui_gtk.mainwindow import MainWindow

pytestmark = pytest.mark.ui


def _iterate(duration: float = 0.2):
    """Runs the main loop for a while."""
    context = GLib.main_context_default()
    end = time.monotonic() + duration
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def _iterate_until_idle(timeout: float = 30.0):
    """Runs the main loop until no task is left."""
    deadline = time.monotonic() + timeout
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "tasks did not finish"
        _iterate(0.05)
    _iterate()


def _paths_dxf(path: Path) -> Path:
    """Two closed polylines and an open line, none touching."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 30), (0, 30)], close=True)
    msp.add_lwpolyline([(60, 0), (90, 0), (90, 20)], close=True)
    msp.add_line((0, 50), (90, 50))
    doc.saveas(path)
    return path


def _two_rects_svg(path: Path) -> Path:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="50mm" viewBox="0 0 100 50">'
        '<rect x="10" y="10" width="20" height="30" fill="none" '
        'stroke="black"/><rect x="60" y="5" width="30" height="20" '
        'fill="none" stroke="black"/></svg>'
    )
    return path


@pytest.fixture
def open_dialog(ui_context_initializer, ui_task_mgr):
    """Opens an ImportDialog on a file; returns it with the kwargs of
    every response it sends."""
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    dialogs = []

    def open_(path, importer, source_asset=None):
        dialog = ImportDialog(
            parent=Gtk.Window(),
            editor=editor,
            file_path=path,
            mime_type=importer.mime_types[0],
            features=importer.features,
            source_asset=source_asset,
        )
        responses = []
        dialog.response.connect(
            lambda sender, **kwargs: responses.append(kwargs), weak=False
        )
        dialogs.append(dialog)
        _iterate_until_idle()
        return dialog, responses

    yield open_

    for dialog in dialogs:
        dialog.destroy()
    _iterate_until_idle()
    editor.cleanup()


def _descendants(widget: Gtk.Widget) -> list[Gtk.Widget]:
    """The widget's descendants, depth first, in layout order."""
    found = []
    child = widget.get_first_child()
    while child is not None:
        found.append(child)
        found.extend(_descendants(child))
        child = child.get_next_sibling()
    return found


class TestTheDialog:
    def test_single_shape_by_default_above_the_layers(
        self, open_dialog, tmp_path
    ):
        dialog, responses = open_dialog(
            _paths_dxf(tmp_path / "paths.dxf"), DxfImporter
        )

        assert dialog.import_as_group.get_visible()
        assert dialog.import_as_row.get_title() == "Import as"
        model = dialog.import_as_row.get_model()
        assert [model.get_string(i) for i in range(model.get_n_items())] == [
            "Single shape",
            "Individual shapes",
        ]
        assert dialog.import_as_row.get_selected() == 0
        assert dialog.layers_group.get_visible()
        order = _descendants(dialog)
        assert order.index(dialog.import_as_group) < order.index(
            dialog.layers_group
        )

        dialog._on_import_clicked(None)

        (response,) = responses
        assert response["response_id"] == "import"
        assert response["split_paths"] is False

    def test_individual_shapes_is_sent(self, open_dialog, tmp_path):
        dialog, responses = open_dialog(
            _paths_dxf(tmp_path / "paths.dxf"), DxfImporter
        )
        dialog.import_as_row.set_selected(1)

        dialog._on_import_clicked(None)

        (response,) = responses
        assert response["split_paths"] is True
        # The choice is not part of the spec, so it is not stored.
        assert not hasattr(response["spec"], "split_paths")

    def test_each_dialog_starts_on_single_shape(self, open_dialog, tmp_path):
        path = _paths_dxf(tmp_path / "paths.dxf")
        first, _ = open_dialog(path, DxfImporter)
        first.import_as_row.set_selected(1)
        first._on_import_clicked(None)

        second, _ = open_dialog(path, DxfImporter)

        assert second.import_as_row.get_selected() == 0

    def test_hidden_when_tracing(self, open_dialog, tmp_path):
        dialog, responses = open_dialog(
            _two_rects_svg(tmp_path / "two.svg"), SvgImporter
        )
        assert dialog.import_as_group.get_visible()
        dialog.import_as_row.set_selected(1)

        dialog.use_vectors_switch.set_active(False)

        assert not dialog.import_as_group.get_visible()
        dialog._on_import_clicked(None)
        (response,) = responses
        assert response["split_paths"] is False

    def test_hidden_on_reimport(self, open_dialog, tmp_path):
        path = _paths_dxf(tmp_path / "paths.dxf")
        source = SourceAsset(
            source_file=path,
            original_data=path.read_bytes(),
            renderer=DXF_RENDERER,
        )

        dialog, responses = open_dialog(path, DxfImporter, source)

        assert not dialog.import_as_group.get_visible()
        dialog._on_import_clicked(None)
        (response,) = responses
        assert response["split_paths"] is False


@pytest.fixture
def win(ui_context_initializer, request):
    """The main window."""

    class TestApp(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    test_name = request.node.name.replace("_", "-")
    app = TestApp(application_id=f"org.swiftcut.swiftcut.test.{test_name}")
    app.register(None)
    app.activate()
    window = app.win
    window.present()
    _iterate(0.5)

    yield window

    window.doc_editor.cleanup()
    # The document has unsaved changes: closing would leave an Unsaved
    # Changes dialog open for the tests after this one.
    window.destroy()
    app.quit()
    _iterate()


def _import(win, path, split_paths):
    """Imports onto the current layer; returns the added workpieces."""
    doc = win.doc_editor.doc
    before = {wp.uid for wp in doc.all_workpieces}
    win.doc_editor.file.load_file_from_path(
        path,
        None,
        PassthroughSpec(layer_import_mode=LayerImportMode.FLATTEN),
        split_paths=split_paths,
    )
    _iterate_until_idle()
    return [wp for wp in doc.all_workpieces if wp.uid not in before]


class TestSelectedOnceImported:
    def test_individual_shapes_are_selected(self, win, tmp_path):
        pieces = _import(win, _paths_dxf(tmp_path / "paths.dxf"), True)

        assert len(pieces) == 3
        assert set(win.surface.get_selected_items()) == set(pieces)

    def test_a_single_shape_import_leaves_the_selection(self, win, tmp_path):
        path = _paths_dxf(tmp_path / "paths.dxf")
        (first,) = _import(win, path, False)
        win.surface.select_items([first])
        _iterate()

        assert len(_import(win, path, False)) == 1

        assert list(win.surface.get_selected_items()) == [first]

    def test_nothing_is_selected_on_a_hidden_layer(self, win, tmp_path):
        win.doc_editor.doc.active_layer.set_visible(False)
        _iterate()

        pieces = _import(win, _paths_dxf(tmp_path / "paths.dxf"), True)

        assert len(pieces) == 3
        assert list(win.surface.get_selected_items()) == []
