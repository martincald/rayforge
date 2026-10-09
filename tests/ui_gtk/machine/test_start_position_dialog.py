"""UI tests for Crawford mode: its toggle, the Start sheet, and the one
way every Start goes through.

With the mode off, Start runs as it always did. With it on, Start asks
whether to run from the head's current position or from where the last
job started.
"""

from unittest.mock import MagicMock, patch

import gi
import pytest

gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402

from swiftcut.machine.models.machine import Machine  # noqa: E402

LAST = (120.0, 80.0)


def _dialog(last_job_start=LAST):
    from swiftcut.ui_gtk.machine.start_position_dialog import (
        StartPositionDialog,
    )

    started = []
    return StartPositionDialog(last_job_start, started.append), started


@pytest.mark.ui
@pytest.mark.parametrize(
    "response, started",
    [("current", [None]), ("last", [LAST]), ("cancel", [])],
)
def test_each_answer_starts_from_its_place(
    ui_context_initializer, response, started
):
    dialog, seen = _dialog()

    dialog.response(response)

    assert seen == started


@pytest.mark.ui
def test_the_last_start_is_offered_only_once_there_is_one(
    ui_context_initializer,
):
    without, _ = _dialog(last_job_start=None)
    with_one, _ = _dialog()

    assert not without.get_response_enabled("last")
    assert without.get_response_enabled("current")
    assert with_one.get_response_enabled("last")


@pytest.mark.ui
def test_enter_and_escape_start_nothing(ui_context_initializer):
    """Both starts fire the laser, so neither is the default."""
    dialog, _ = _dialog()

    assert dialog.get_default_response() == "cancel"
    assert dialog.get_close_response() == "cancel"


@pytest.mark.ui
def test_the_sheet_looks_like_the_cut_scale_sheet(ui_context_initializer):
    dialog, _ = _dialog()

    assert dialog.has_css_class("sc-sheet")
    for response in ("current", "last"):
        assert (
            dialog.get_response_appearance(response)
            == Adw.ResponseAppearance.DESTRUCTIVE
        )


@pytest.mark.ui
def test_with_the_mode_off_start_runs_at_once_with_no_sheet(
    ui_context_initializer,
):
    from swiftcut.ui_gtk.machine import start_position_dialog

    assert ui_context_initializer.config.crawford_mode is False
    run = MagicMock()

    with patch.object(start_position_dialog, "StartPositionDialog") as cls:
        start_position_dialog.request_start(None, MagicMock(), run)

    run.assert_called_once_with(None)
    cls.assert_not_called()


@pytest.mark.ui
def test_with_the_mode_on_start_asks_first(ui_context_initializer):
    from swiftcut.ui_gtk.machine import start_position_dialog

    ui_context_initializer.config.set_crawford_mode(True)
    machine = MagicMock(last_job_start=LAST)
    run = MagicMock()

    with patch.object(start_position_dialog, "StartPositionDialog") as cls:
        start_position_dialog.request_start(None, machine, run)

    run.assert_not_called()
    cls.assert_called_once()
    last_job_start, on_start = cls.call_args.args
    assert last_job_start == LAST
    cls.return_value.present.assert_called_once()
    # The sheet's answer is the Start.
    on_start(LAST)
    run.assert_called_once_with(LAST)


def _general_page(context):
    from swiftcut.ui_gtk.machine.general_preferences_page import (
        GeneralPreferencesPage,
    )

    machine = Machine(context)
    context.machine_mgr.add_machine(machine)
    return GeneralPreferencesPage(machine)


@pytest.mark.ui
def test_the_general_page_has_the_toggle_off(ui_context_initializer):
    page = _general_page(ui_context_initializer)

    assert page.crawford_row.get_title() == "Crawford mode"
    assert page.crawford_row.get_subtitle()
    assert not page.crawford_row.get_active()


@pytest.mark.ui
def test_the_toggle_turns_the_mode_on_and_off(ui_context_initializer):
    config = ui_context_initializer.config
    page = _general_page(ui_context_initializer)

    page.crawford_row.set_active(True)
    assert config.crawford_mode is True
    saved = ui_context_initializer.config_mgr.filepath.read_text()
    assert "crawford_mode: true" in saved

    page.crawford_row.set_active(False)
    assert config.crawford_mode is False


@pytest.mark.ui
def test_the_toggle_shows_the_saved_mode(ui_context_initializer):
    ui_context_initializer.config.set_crawford_mode(True)

    page = _general_page(ui_context_initializer)

    assert page.crawford_row.get_active()
