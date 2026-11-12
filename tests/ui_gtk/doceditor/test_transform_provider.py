# flake8: noqa: E402
"""UI tests for the Width/Height rows of the transform properties."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from raygeo.geo import Matrix

from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.ui_gtk.doceditor.property_providers.transform import (
    TransformPropertyProvider,
)


@pytest.fixture
def editor(ui_context_initializer, ui_task_mgr, monkeypatch):
    ui_context_initializer.config.unit_preferences["length"] = "mm"
    # The Fixed Ratio choice is session state; each test gets its own.
    monkeypatch.setattr(
        TransformPropertyProvider,
        "fixed_ratio",
        TransformPropertyProvider.fixed_ratio,
    )
    editor = DocEditor(
        task_manager=ui_task_mgr, context=ui_context_initializer
    )
    yield editor
    editor.cleanup()


def _workpiece(editor, width=100.0, height=50.0):
    wp = WorkPiece(name="wp.svg")
    wp.matrix = Matrix.scale(width, height)
    editor.doc.active_layer.add_child(wp)
    return wp


def _provider(editor, items):
    provider = TransformPropertyProvider()
    provider.create_widgets()
    provider.update_widgets(editor, items)
    return provider


def _type_and_commit(row, text):
    row.get_spin_button().set_text(text)
    row.numeric_entry.commit()


@pytest.mark.ui
def test_fixed_ratio_starts_off(editor):
    assert TransformPropertyProvider.fixed_ratio is False
    provider = _provider(editor, [_workpiece(editor)])
    assert provider.fixed_ratio_switch.get_active() is False


@pytest.mark.ui
def test_height_alone_changes_with_fixed_ratio_off(editor):
    wp = _workpiece(editor)
    provider = _provider(editor, [wp])

    _type_and_commit(provider.height_row, "80")

    assert wp.size == pytest.approx((100.0, 80.0))


@pytest.mark.ui
def test_width_follows_height_with_fixed_ratio_on(editor):
    wp = _workpiece(editor)
    provider = _provider(editor, [wp])
    provider.fixed_ratio_switch.set_active(True)

    _type_and_commit(provider.height_row, "100")

    assert wp.size == pytest.approx((200.0, 100.0))


@pytest.mark.ui
def test_fixed_ratio_survives_a_selection_change(editor):
    first = _workpiece(editor)
    second = _workpiece(editor, 30.0, 60.0)
    provider = _provider(editor, [first])
    provider.fixed_ratio_switch.set_active(True)

    provider.update_widgets(editor, [second])

    assert provider.fixed_ratio_switch.get_active() is True
    _type_and_commit(provider.width_row, "60")
    assert second.size == pytest.approx((60.0, 120.0))


@pytest.mark.ui
def test_a_new_provider_starts_from_the_session_choice(editor):
    wp = _workpiece(editor)
    _provider(editor, [wp]).fixed_ratio_switch.set_active(True)

    assert _provider(editor, [wp]).fixed_ratio_switch.get_active() is True


@pytest.mark.ui
def test_typing_resizes_only_on_commit_in_one_undo_step(editor):
    wp = _workpiece(editor)
    provider = _provider(editor, [wp])
    history = editor.history_manager
    entries = len(history.undo_stack)
    spin = provider.width_row.get_spin_button()

    for text in ("1", "12", "125"):
        spin.set_text(text)
    assert wp.size == pytest.approx((100.0, 50.0))
    assert len(history.undo_stack) == entries

    provider.width_row.numeric_entry.commit()

    assert wp.size == pytest.approx((125.0, 50.0))
    assert len(history.undo_stack) == entries + 1
