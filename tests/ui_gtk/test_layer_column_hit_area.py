"""A layer card is short; the layer's drop and click area is not.

The card is drawn only as tall as its content, but a drop, a click
(make active) or a right-click (Paste) anywhere in the column below it
still lands on that layer, as it did when the card filled the dock.
"""

import pytest


def _settle(widget):
    from gi.repository import GLib

    context = GLib.MainContext.default()
    for _ in range(200):
        while context.pending():
            context.iteration(False)
        if widget.get_height() > 0:
            break


@pytest.mark.ui
def test_the_column_below_a_short_card_is_still_the_layers(
    ui_context_initializer, ui_task_mgr
):
    from gi.repository import Gtk

    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk.doceditor.layers_tab import LayersTab

    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    tab = LayersTab(editor)
    window = Gtk.Window(child=tab, default_width=900, default_height=400)
    try:
        window.present()
        column = tab._columns[0]
        _settle(column)
        _settle(column.card)

        below_card = column.card.get_height() + 20
        assert column.card.get_height() < column.get_height() / 2
        assert below_card < column.get_height()
        assert column.pick(10, below_card, Gtk.PickFlags.DEFAULT) is column
        controllers = list(column.observe_controllers())
        assert any(isinstance(c, Gtk.DropTarget) for c in controllers)
        assert any(isinstance(c, Gtk.GestureClick) for c in controllers)
    finally:
        window.destroy()
        editor.cleanup()
