"""The Layers tab keeps up with many pieces: adding a piece rebuilds
its layer's rows once, not once per column ever built. Columns are
rebuilt only when the layers change, and a replaced column lets go of
its layer (GTK 4 never calls do_destroy on its own).
"""

import pytest

from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.ui_gtk.doceditor.layer_column import LayerColumn
from swiftcut.ui_gtk.doceditor.layers_tab import LayersTab

pytestmark = pytest.mark.ui


@pytest.fixture
def tab(ui_context_initializer, ui_task_mgr, monkeypatch):
    """A Layers tab on a fresh document; returns it with a list that
    gets the column of every row rebuild."""
    rebuilt = []
    rebuild = LayerColumn._rebuild_workpiece_list

    def counting(column):
        rebuilt.append(column)
        rebuild(column)

    monkeypatch.setattr(LayerColumn, "_rebuild_workpiece_list", counting)
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    yield LayersTab(editor), editor, rebuilt
    editor.cleanup()


def _column_of(tab, layer):
    (column,) = [c for c in tab._columns if c.layer is layer]
    return column


def test_each_added_piece_rebuilds_its_rows_once(tab):
    tab, editor, rebuilt = tab
    columns = list(tab._columns)
    layer = editor.doc.active_layer
    rebuilt.clear()

    for n in range(10):
        layer.add_child(WorkPiece(name=f"wp{n}"))

    assert tab._columns == columns
    assert rebuilt == [_column_of(tab, layer)] * 10


def test_a_replaced_column_lets_go_of_its_layer(tab):
    tab, editor, rebuilt = tab
    layer = editor.doc.active_layer
    old = _column_of(tab, layer)

    editor.doc.add_layer(Layer("Second"))
    assert old not in tab._columns
    rebuilt.clear()
    layer.add_child(WorkPiece(name="wp"))

    assert rebuilt == [_column_of(tab, layer)]
