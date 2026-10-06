"""
The file dialog and the canvas drop share one import entry,
import_handler.import_files, so the same file imports the same way.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from gi.repository import Adw, Gio, Gtk
from raygeo.geo import Matrix

from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.ui_gtk.canvas2d.drag_drop_cmd import DragDropCmd
from swiftcut.ui_gtk.doceditor import import_handler

TESTS_DIR = Path(__file__).parent.parent.parent
SWITCH_PLATE = (
    TESTS_DIR / "image" / "lightburn" / "assets" / "switch_plate.lbrn2"
)
ARC_DXF = TESTS_DIR / "image" / "dxf" / "acdbarc.dxf"


def _accept_import_dialog(win, editor, file_path, mime_type, position_mm=None):
    """Stands in for the ImportDialog: the user clicks Import."""
    import_handler._on_import_dialog_response(
        None,
        "import",
        PassthroughSpec(),
        win,
        editor,
        file_path,
        mime_type,
        position_mm,
    )


async def _settle(editor, task_mgr, timeout=30.0):
    """Waits until the import tasks and the pipeline are done."""
    deadline = time.monotonic() + timeout
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "import did not finish"
        await asyncio.sleep(0.01)
    await editor.wait_until_settled()


async def _import_via(editor, task_mgr, entry):
    """Runs one import entry; returns the workpieces it added."""
    before = {wp.uid for wp in editor.doc.all_workpieces}
    with patch.object(
        import_handler,
        "_start_interactive_import",
        side_effect=_accept_import_dialog,
    ):
        entry()
    await _settle(editor, task_mgr)
    return [wp for wp in editor.doc.all_workpieces if wp.uid not in before]


def _outlines(workpieces):
    """World outlines, moved so the import's bbox starts at 0, 0."""
    geos = [wp.get_world_geometry() for wp in workpieces]
    x0 = min(geo.rect()[0] for geo in geos)
    y0 = min(geo.rect()[1] for geo in geos)
    shift = Matrix.translation(-x0, -y0)
    return [geo.copy().transform(shift).to_dict()["commands"] for geo in geos]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", [SWITCH_PLATE, ARC_DXF], ids=lambda p: p.suffix
)
async def test_dialog_and_drop_import_the_same(
    path, doc_editor, task_mgr, test_machine_and_config
):
    """
    The same file through the file dialog and through a canvas drop
    gives the same outlines at the same size. Only the position differs
    by design: the dialog anchors at the reference origin, the drop
    centers on the drop point.
    """
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    win = MagicMock()
    win.doc_editor = doc_editor

    dialog = MagicMock()
    dialog.open_finish.return_value = Gio.File.new_for_path(str(path))
    from_dialog = await _import_via(
        doc_editor,
        task_mgr,
        lambda: import_handler._on_file_selected(
            dialog, None, (win, doc_editor)
        ),
    )

    surface = MagicMock()
    surface._get_world_coords.return_value = (700.0, 450.0)
    with patch.object(DragDropCmd, "_apply_drop_overlay_css"):
        drop_cmd = DragDropCmd(win, surface)
    dropped = await _import_via(
        doc_editor,
        task_mgr,
        lambda: drop_cmd._on_drop(
            None, Gio.File.new_for_path(str(path)), 10, 20
        ),
    )

    assert from_dialog
    assert [wp.size for wp in dropped] == pytest.approx(
        [wp.size for wp in from_dialog]
    )
    dialog_outlines = _outlines(from_dialog)
    drop_outlines = _outlines(dropped)
    assert len(drop_outlines) == len(dialog_outlines)
    for expected, actual in zip(dialog_outlines, drop_outlines, strict=True):
        assert [cmd[0] for cmd in actual] == [cmd[0] for cmd in expected]
        assert [cmd[1:] for cmd in actual] == [
            pytest.approx(cmd[1:], abs=1e-6) for cmd in expected
        ]


@pytest.fixture
def file_cmd_editor(context_initializer):
    """A DocEditor whose task manager is a mock (nothing runs)."""
    from swiftcut.core.doc import Doc
    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.shared.tasker.manager import TaskManager

    editor = DocEditor(MagicMock(spec=TaskManager), context_initializer, Doc())
    yield editor
    editor.cleanup()


def test_unsupported_files_are_skipped(file_cmd_editor, tmp_path):
    """
    Files no importer supports are skipped, and reported as such. On
    macOS an unknown suffix must not reach the Ruida importer through
    application/octet-stream.
    """
    path = tmp_path / "notes.xyz"
    path.write_bytes(b"\x00\x01not a drawing")
    win = MagicMock()

    with patch.object(import_handler, "import_file_at_position") as route:
        imported = import_handler.import_files(
            win, file_cmd_editor, [Gio.File.new_for_path(str(path))]
        )

    assert imported is False
    route.assert_not_called()


def _message_dialogs():
    return [
        window
        for window in Gtk.Window.list_toplevels()
        if isinstance(window, Adw.MessageDialog)
    ]


@pytest.mark.ui
@pytest.mark.parametrize(
    "response, scale", [("scale", True), ("cancel", False)]
)
def test_oversize_dialog_answers_scale_or_cancel(response, scale):
    """The dialog offers Scale to fit and Cancel; closing it cancels.
    It returns at once and answers on the response."""
    answers = []
    import_handler.ask_scale_to_fit(
        None,
        Path("big.svg"),
        (2000.0, 1000.0),
        (1400.0, 900.0),
        answers.append,
    )
    (dialog,) = _message_dialogs()
    try:
        assert answers == []
        assert dialog.has_response("scale")
        assert dialog.has_response("cancel")
        assert dialog.get_close_response() == "cancel"
        assert "2000 x 1000 mm" in dialog.get_body()
        assert "1400 x 900 mm" in dialog.get_body()

        dialog.response(response)

        assert answers == [scale]
    finally:
        dialog.destroy()
