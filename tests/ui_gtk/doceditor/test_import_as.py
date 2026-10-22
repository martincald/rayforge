# flake8: noqa: E402
"""
The import dialog's "Import as", above the layer list. A file with
structure (SVG, DXF): By source layers and groups (the default, every
time), Pieces, Individual shapes or Single shape, with their options;
any other file: Single shape (the default, every time) or Individual
shapes. Individual shapes are selected once imported. Direct vector
imports only.
"""

import base64
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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
import pyvips

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from swiftcut.core.source_asset import SourceAsset
from swiftcut.core.vectorization_spec import (
    LayerImportMode,
    PassthroughSpec,
    TraceSpec,
)
from swiftcut.doceditor.editor import DocEditor
from swiftcut.doceditor.import_materializer import (
    ImportGrouping,
    ImportOptions,
    options_for,
)
from swiftcut.image.dxf.importer import DxfImporter
from swiftcut.image.dxf.renderer import DXF_RENDERER
from swiftcut.image.lightburn.importer import LightBurnImporter
from swiftcut.image.svg.importer import SvgImporter
from swiftcut.shared.tasker import task_mgr
from swiftcut.ui_gtk.doceditor import import_handler
from swiftcut.ui_gtk.doceditor.import_dialog import ImportDialog
from swiftcut.ui_gtk.mainwindow import MainWindow

pytestmark = pytest.mark.ui

TESTS_DIR = Path(__file__).parent.parent.parent
FIXTURES = TESTS_DIR / "fixtures" / "import"
ILLUSTRATOR = FIXTURES / "illustrator_two_layers.svg"
TRACED = FIXTURES / "illustrator_traced.dxf"
PLATES = FIXTURES / "cad_plate.dxf"
SWITCH_PLATE = (
    TESTS_DIR / "image" / "lightburn" / "assets" / "switch_plate.lbrn2"
)
FOUR_WAY = [
    "By source layers and groups",
    "Pieces",
    "Individual shapes",
    "Single shape",
]
FALLBACK = "No layers or groups in this file; grouping by pieces"


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


def _two_layers_dxf(path: Path) -> Path:
    """A rect on layer Cut, a smaller one on layer Engrave."""
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    for name, size in (("Cut", 40), ("Engrave", 20)):
        doc.layers.add(name)
        msp.add_lwpolyline(
            [(0, 0), (size, 0), (size, size), (0, size)],
            close=True,
            dxfattribs={"layer": name},
        )
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


def _choices(row) -> list[str]:
    model = row.get_model()
    return [model.get_string(i) for i in range(model.get_n_items())]


def _choose(dialog, label):
    """Selects an "Import as" choice and waits for the preview."""
    dialog.import_as_row.set_selected(
        _choices(dialog.import_as_row).index(label)
    )
    _iterate_until_idle()


class TestTheDialog:
    @pytest.mark.parametrize(
        "make, importer",
        [
            (_two_layers_dxf, DxfImporter),
            (lambda path: _layer_svg(path, 2), SvgImporter),
        ],
        ids=["dxf", "svg"],
    )
    def test_by_source_by_default_above_the_layers(
        self, open_dialog, tmp_path, make, importer
    ):
        dialog, responses = open_dialog(
            make(tmp_path / f"file{importer.extensions[0]}"), importer
        )

        assert dialog.import_as_group.get_visible()
        assert dialog.import_as_row.get_title() == "Import as"
        assert _choices(dialog.import_as_row) == FOUR_WAY
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
        assert response["options"] == ImportOptions(
            grouping=ImportGrouping.BY_SOURCE,
            interior_on_own_layer=False,
            keep_images=importer is SvgImporter,
            layer_per_source_layer=True,
        )

    def test_the_options_and_where_they_apply(self, open_dialog, tmp_path):
        dialog, _ = open_dialog(
            _layer_svg(tmp_path / "two.svg", 2), SvgImporter
        )
        rows = (
            dialog.interior_row,
            dialog.keep_images_row,
            dialog.layer_per_source_row,
        )
        assert [row.get_title() for row in rows] == [
            "Put interior details on their own layer (engrave)",
            "Keep images as rasters",
            "Create a SwiftCut layer per source layer",
        ]
        assert [row.get_active() for row in rows] == [False, True, True]
        sensitive = {
            "By source layers and groups": [True, True, True],
            "Pieces": [True, True, False],
            "Individual shapes": [False, True, False],
            "Single shape": [False, True, False],
        }

        for label, expected in sensitive.items():
            _choose(dialog, label)

            assert [row.get_visible() for row in rows] == [True] * 3
            assert [row.get_sensitive() for row in rows] == expected, label

    def test_keep_images_is_hidden_for_a_dxf(self, open_dialog, tmp_path):
        dialog, _ = open_dialog(
            _paths_dxf(tmp_path / "paths.dxf"), DxfImporter
        )

        assert not dialog.keep_images_row.get_visible()
        assert dialog.interior_row.get_visible()
        assert dialog.layer_per_source_row.get_visible()

    @pytest.mark.parametrize(
        "label, grouping",
        [
            ("Pieces", ImportGrouping.PIECES),
            ("Individual shapes", ImportGrouping.INDIVIDUAL),
            ("Single shape", ImportGrouping.SINGLE),
        ],
    )
    def test_the_choice_and_its_options_are_sent(
        self, open_dialog, tmp_path, label, grouping
    ):
        dialog, responses = open_dialog(
            _two_rects_svg(tmp_path / "two.svg"), SvgImporter
        )
        _choose(dialog, label)
        dialog.keep_images_row.set_active(False)

        dialog._on_import_clicked(None)

        (response,) = responses
        assert response["split_paths"] is (
            grouping is ImportGrouping.INDIVIDUAL
        )
        assert response["options"].grouping is grouping
        assert response["options"].keep_images is False
        # The choice is not part of the spec, so it is not stored.
        assert not hasattr(response["spec"], "split_paths")

    def test_each_dialog_starts_on_by_source(self, open_dialog, tmp_path):
        path = _layer_svg(tmp_path / "two.svg", 2)
        first, _ = open_dialog(path, SvgImporter)
        _choose(first, "Pieces")
        first.interior_row.set_active(True)
        first.keep_images_row.set_active(False)
        first._on_import_clicked(None)

        second, responses = open_dialog(path, SvgImporter)

        assert second.import_as_row.get_selected() == 0
        assert not second.interior_row.get_active()
        assert second.keep_images_row.get_active()
        second._on_import_clicked(None)
        (response,) = responses
        assert response["options"] == ImportOptions(
            grouping=ImportGrouping.BY_SOURCE
        )

    def test_a_file_without_structure_keeps_two_choices(self, open_dialog):
        """
        LightBurn files have no import tree: Single shape (every time)
        or Individual shapes, without options, imported as before.
        """
        dialog, responses = open_dialog(SWITCH_PLATE, LightBurnImporter)

        assert dialog.import_as_group.get_visible()
        assert _choices(dialog.import_as_row) == [
            "Single shape",
            "Individual shapes",
        ]
        assert dialog.import_as_row.get_selected() == 0
        for row in (
            dialog.interior_row,
            dialog.keep_images_row,
            dialog.layer_per_source_row,
        ):
            assert not row.get_visible()
        dialog._on_import_clicked(None)
        _choose(dialog, "Individual shapes")
        dialog._on_import_clicked(None)

        single, individual = responses
        assert single["split_paths"] is False
        assert single["options"] == options_for(None, split_paths=False)
        assert individual["split_paths"] is True
        assert individual["options"] == options_for(None, split_paths=True)

    def test_hidden_when_tracing(self, open_dialog, tmp_path):
        dialog, responses = open_dialog(
            _two_rects_svg(tmp_path / "two.svg"), SvgImporter
        )
        assert dialog.import_as_group.get_visible()
        _choose(dialog, "Individual shapes")

        dialog.use_vectors_switch.set_active(False)

        assert not dialog.import_as_group.get_visible()
        dialog._on_import_clicked(None)
        (response,) = responses
        assert isinstance(response["spec"], TraceSpec)
        assert response["split_paths"] is False
        assert response["options"] == options_for(None)

    def test_hidden_on_reimport(self, open_dialog, tmp_path):
        path = _paths_dxf(tmp_path / "paths.dxf")
        source = SourceAsset(
            source_file=path,
            original_data=path.read_bytes(),
            renderer=DXF_RENDERER,
        )

        dialog, responses = open_dialog(path, DxfImporter, source)

        assert not dialog.import_as_group.get_visible()
        assert dialog.layer_import_mode_row.get_sensitive()
        assert dialog.layer_import_mode_row.get_selected() == 0
        dialog._on_import_clicked(None)
        (response,) = responses
        assert response["split_paths"] is False
        assert response["options"] == options_for(None)


def _layer_svg(path: Path, layers: int) -> Path:
    """A red and a blue rect, grouped, in each of that many layers."""
    rects = (
        '<rect x="10" y="10" width="20" height="20" fill="none" '
        'stroke="#ff0000"/><rect x="50" y="10" width="20" height="20" '
        'fill="none" stroke="#0000ff"/>'
    )
    body = "".join(f'<g id="L{i}"><g>{rects}</g></g>' for i in range(layers))
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        f'height="50mm" viewBox="0 0 100 50">{body}</svg>'
    )
    return path


def _listed_layers(dialog) -> list[str]:
    return sorted(dialog._layer_widgets.values())


class TestBySourceReadsTheFilesLayers:
    def test_the_layer_rows_show_it_and_are_locked(
        self, open_dialog, tmp_path
    ):
        dialog, _ = open_dialog(
            _layer_svg(tmp_path / "two.svg", 2), SvgImporter
        )

        assert dialog.layer_source_row.get_selected() == 0  # SVG Layers
        assert dialog.layer_import_mode_row.get_selected() == 1  # New
        assert not dialog.layer_source_row.get_sensitive()
        assert not dialog.layer_import_mode_row.get_sensitive()
        assert _listed_layers(dialog) == ["L0", "L1"]
        spec = dialog._get_current_spec()
        assert spec.layer_import_mode is LayerImportMode.NEW_LAYERS

        dialog.layer_per_source_row.set_active(False)
        _iterate_until_idle()

        assert dialog.layer_import_mode_row.get_selected() == 2  # Flatten
        spec = dialog._get_current_spec()
        assert spec.layer_import_mode is LayerImportMode.FLATTEN

    def test_other_modes_get_the_rows_back(self, open_dialog, tmp_path):
        dialog, _ = open_dialog(
            _layer_svg(tmp_path / "two.svg", 2), SvgImporter
        )

        _choose(dialog, "Pieces")

        assert dialog.layer_source_row.get_sensitive()
        assert dialog.layer_import_mode_row.get_sensitive()
        assert dialog.layer_import_mode_row.get_selected() == 0  # Map
        dialog.layer_import_mode_row.set_selected(2)
        _choose(dialog, "By source layers and groups")
        assert dialog.layer_import_mode_row.get_selected() == 1
        _choose(dialog, "Single shape")
        assert dialog.layer_import_mode_row.get_selected() == 2

    def test_one_layer_lists_colors_in_other_modes_only(
        self, open_dialog, tmp_path
    ):
        """
        A file of one layer and two colors starts on Colors, as before,
        in every mode but By source, which lists the file's layer.
        """
        dialog, _ = open_dialog(
            _layer_svg(tmp_path / "one.svg", 1), SvgImporter
        )

        assert dialog.layer_source_row.get_selected() == 0
        assert _listed_layers(dialog) == ["L0"]

        _choose(dialog, "Pieces")

        assert dialog.layer_source_row.get_selected() == 1  # Colors
        assert _listed_layers(dialog) == ["#0000ff", "#ff0000"]
        assert isinstance(dialog._get_current_spec(), PassthroughSpec)


class TestBySourceWithNothingToGoBy:
    """
    By source of a file without layers or groups is Pieces, once the
    preview has read the file: the layer rows are Pieces' own, and the
    import is a Pieces import.
    """

    @pytest.mark.parametrize("make", [None, _two_rects_svg])
    def test_it_is_pieces(self, open_dialog, tmp_path, make):
        path = make(tmp_path / "two.svg") if make else PLATES
        importer = SvgImporter if make else DxfImporter
        dialog, responses = open_dialog(path, importer)

        assert dialog.import_as_row.get_selected() == 0
        assert dialog.import_as_row.get_subtitle() == FALLBACK
        assert dialog.layer_source_row.get_sensitive()
        assert dialog.layer_import_mode_row.get_sensitive()
        assert dialog.interior_row.get_sensitive()
        assert not dialog.layer_per_source_row.get_sensitive()
        by_source = dialog._get_current_spec()
        dialog._on_import_clicked(None)
        _choose(dialog, "Pieces")
        dialog._on_import_clicked(None)

        sent, pieces = responses
        assert sent["options"] == pieces["options"]
        assert sent["options"].grouping is ImportGrouping.PIECES
        assert sent["spec"] == pieces["spec"] == by_source

    def test_the_layer_rows_keep_their_values(self, open_dialog, tmp_path):
        """
        Two rects of one color, no layers: Colors and Map to Existing,
        as Pieces has them.
        """
        dialog, _ = open_dialog(
            _two_rects_svg(tmp_path / "two.svg"), SvgImporter
        )

        assert dialog.layer_source_row.get_selected() == 1  # Colors
        assert dialog.layer_import_mode_row.get_selected() == 0  # Map
        assert _listed_layers(dialog) == ["#000000"]


class TestNotices:
    def test_by_source_without_layers_or_groups_says_pieces(self, open_dialog):
        dialog, _ = open_dialog(PLATES, DxfImporter)

        assert dialog.import_as_row.get_subtitle() == FALLBACK

        _choose(dialog, "Pieces")

        assert dialog.import_as_row.get_subtitle() == ""

    def test_a_file_with_layers_says_nothing(self, open_dialog):
        dialog, _ = open_dialog(ILLUSTRATOR, SvgImporter)

        assert dialog.import_as_row.get_subtitle() == ""

    def test_what_will_not_be_imported_is_shown(self, open_dialog, tmp_path):
        path = tmp_path / "text.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
            'height="50mm" viewBox="0 0 100 50"><rect x="10" y="10" '
            'width="20" height="20" fill="none" stroke="#000"/>'
            '<text x="40" y="20">Hello &amp; bye</text></svg>'
        )

        dialog, _ = open_dialog(path, SvgImporter)

        banner = dialog.import_warning_banner
        assert banner.get_revealed()
        assert banner.get_title() == (
            'Text "Hello & bye" is not outlined and was not imported. In '
            "Illustrator: Type > Create Outlines."
        )

    @pytest.mark.parametrize(
        "path, importer, hinted",
        [
            (ILLUSTRATOR, SvgImporter, False),
            (TRACED, DxfImporter, True),
            (PLATES, DxfImporter, False),
        ],
        ids=lambda v: v.name if isinstance(v, Path) else None,
    )
    def test_traced_artwork_is_hinted(
        self, open_dialog, path, importer, hinted
    ):
        dialog, _ = open_dialog(path, importer)

        assert dialog.traced_banner.get_revealed() is hinted
        assert not dialog.import_warning_banner.get_revealed()
        assert dialog.traced_banner.get_title() == (
            "This looks like traced artwork. Exporting SVG from "
            "Illustrator keeps images as images and engraves better."
        )

    def test_the_hint_is_dismissed_and_blocks_nothing(self, open_dialog):
        dialog, responses = open_dialog(TRACED, DxfImporter)
        assert dialog.import_button.get_sensitive()

        dialog.traced_banner.emit("button-clicked")

        assert not dialog.traced_banner.get_revealed()
        _choose(dialog, "Pieces")
        assert not dialog.traced_banner.get_revealed()
        dialog._on_import_clicked(None)
        assert len(responses) == 1


@pytest.fixture
def import_from_dialog(ui_context_initializer, ui_task_mgr):
    """
    Imports a file through the import handler's dialog: opens it,
    lets a choice be made, clicks Import and waits for the import.
    Returns the editor and the dialog.
    """
    ui_context_initializer.machine.set_axis_extents(1400, 900)
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    parent = Gtk.Window()
    parent.item_revealer = MagicMock()
    dialogs = []
    make_dialog = import_handler.ImportDialog

    def open_dialog(**kwargs):
        dialogs.append(make_dialog(**kwargs))
        return dialogs[-1]

    def import_(path, importer, choose=None):
        with patch.object(
            import_handler, "ImportDialog", side_effect=open_dialog
        ):
            import_handler._start_interactive_import(
                parent, editor, path, importer.mime_types[0]
            )
        dialog = dialogs[-1]
        _iterate_until_idle()
        if choose is not None:
            choose(dialog)
            _iterate_until_idle()
        assert dialog.import_button.get_sensitive()
        dialog.import_button.emit("clicked")
        _iterate_until_idle()
        return dialog

    yield editor, import_

    for dialog in dialogs:
        dialog.destroy()
    parent.destroy()
    _iterate_until_idle()
    editor.cleanup()


def _vectors_and_images(workpieces):
    """The workpieces split into vector ones and image ones."""
    images = [
        wp
        for wp in workpieces
        if isinstance(wp.source_segment.vectorization_spec, TraceSpec)
    ]
    return [wp for wp in workpieces if wp not in images], images


def _contours(wp) -> int:
    return len(wp.boundaries.split_into_contours())


class TestImportedFromTheDialog:
    def test_by_source_is_one_undo_step(self, import_from_dialog):
        """
        The Illustrator file by default: its layers Cut and Engrave as
        SwiftCut layers, Engrave's groups one piece each, its PNG an
        image workpiece; everything in one undo step.
        """
        editor, import_ = import_from_dialog
        doc = editor.doc
        layers = list(doc.layers)
        history = editor.history_manager
        entries = len(history.undo_stack)

        import_(ILLUSTRATOR, SvgImporter)

        new_layers = doc.layers[len(layers) :]
        assert [layer.name for layer in new_layers] == ["Cut", "Engrave"]
        cut, engrave = new_layers
        (outline,) = cut.all_workpieces
        groups, (image,) = _vectors_and_images(engrave.all_workpieces)
        assert _contours(outline) == 1
        assert sorted(_contours(wp) for wp in groups) == [3, 3]
        assert image.source_layer == "Engrave"
        assert len(history.undo_stack) == entries + 1

        history.undo()

        assert doc.layers == layers
        assert doc.all_workpieces == []

    def test_a_flat_cad_file_comes_in_as_pieces(self, import_from_dialog):
        """
        cad_plate.dxf: two plates, each outline with its holes, on the
        current layer as Pieces puts them; no layer "0".
        """
        editor, import_ = import_from_dialog
        layers = list(editor.doc.layers)
        before = set(editor.doc.all_workpieces)

        dialog = import_(PLATES, DxfImporter)

        added = [wp for wp in editor.doc.all_workpieces if wp not in before]
        assert dialog.import_as_row.get_subtitle() == FALLBACK
        assert editor.doc.layers == layers
        assert {wp.layer for wp in added} == {editor.doc.active_layer}
        assert sorted(_contours(wp) for wp in added) == [4, 5]
        assert sorted(wp.size for wp in added) == [
            pytest.approx((80, 50)),
            pytest.approx((100, 60)),
        ]

    def test_single_is_one_shape_per_layer(self, import_from_dialog):
        """As before, plus the kept image."""
        editor, import_ = import_from_dialog

        import_(
            ILLUSTRATOR,
            SvgImporter,
            lambda dialog: _choose(dialog, "Single shape"),
        )

        vectors, images = _vectors_and_images(editor.doc.all_workpieces)
        assert sorted(wp.source_segment.layer_id for wp in vectors) == [
            "Cut",
            "Engrave",
        ]
        assert sorted(_contours(wp) for wp in vectors) == [1, 6]
        assert len(images) == 1

    def test_individual_is_one_shape_per_path(self, import_from_dialog):
        editor, import_ = import_from_dialog

        import_(
            ILLUSTRATOR,
            SvgImporter,
            lambda dialog: _choose(dialog, "Individual shapes"),
        )

        vectors, images = _vectors_and_images(editor.doc.all_workpieces)
        assert len(vectors) == 7
        assert len(images) == 1

    def test_interior_details_go_to_an_engrave_layer(self, import_from_dialog):
        """The traced DXF as Pieces: the dots on an engrave layer."""
        editor, import_ = import_from_dialog
        layers = list(editor.doc.layers)

        def choose(dialog):
            _choose(dialog, "Pieces")
            dialog.interior_row.set_active(True)

        import_(TRACED, DxfImporter, choose)

        (engrave,) = editor.doc.layers[len(layers) :]
        assert engrave.name == "illustrator_traced engrave"
        (dots,) = engrave.all_workpieces
        assert _contours(dots) == 120
        (step,) = engrave.workflow.steps
        assert type(step).__name__ == "EngraveStep"


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


def _image_svg(path: Path, transform: str) -> Path:
    """A frame, and a PNG placed in it under a transform."""
    grey = (pyvips.Image.black(40, 20) + 128).cast("uchar")
    png = base64.b64encode(grey.pngsave_buffer()).decode()
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="100mm" viewBox="0 0 100 100"><g id="L">'
        '<rect x="0" y="0" width="100" height="100" fill="none" '
        'stroke="#000"/><image id="Photo" x="20" y="30" width="60" '
        f'height="30" transform="{transform}" '
        f'href="data:image/png;base64,{png}"/></g></svg>'
    )
    return path


@pytest.mark.parametrize(
    "transform, warned",
    [
        ("rotate(30 50 45)", True),
        ("scale(-1 1) translate(-100 0)", True),
        ("translate(5 5)", False),
    ],
)
def test_an_image_that_will_be_skipped_is_said(
    open_dialog, tmp_path, transform, warned
):
    dialog, _ = open_dialog(
        _image_svg(tmp_path / "photo.svg", transform), SvgImporter
    )

    banner = dialog.import_warning_banner
    assert banner.get_revealed() is warned
    if warned:
        assert banner.get_title() == (
            'Image "Photo" is rotated, skewed or flipped and was not imported.'
        )
