"""The test cut's sheet: styled like Cut Scale's, Cancel by default.

It names the layer and the settings the square is cut at, and offers
Cancel, Choose Spot... and Cut; only Cut fires the laser.
"""

from unittest.mock import MagicMock

import gi
import pytest

gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402


def _dialog():
    from swiftcut.ui_gtk.machine import testcut_dialog

    on_cut, on_pick = MagicMock(), MagicMock()
    # 1200 mm/min is 20 mm/s.
    dialog = testcut_dialog.TestCutDialog(
        "Cut layer", 1200.0, 0.45, 0.3, on_cut=on_cut, on_pick=on_pick
    )
    return dialog, on_cut, on_pick


@pytest.mark.ui
@pytest.mark.parametrize(
    "response, cut, pick",
    [("cut", 1, 0), ("pick", 0, 1), ("cancel", 0, 0)],
)
def test_each_answer_does_only_its_own_thing(
    ui_context_initializer, response, cut, pick
):
    dialog, on_cut, on_pick = _dialog()

    dialog.response(response)

    assert (on_cut.call_count, on_pick.call_count) == (cut, pick)


@pytest.mark.ui
def test_enter_and_escape_cut_nothing(ui_context_initializer):
    """Cut fires the laser, so Cancel is the default and close."""
    dialog, _on_cut, _on_pick = _dialog()

    assert dialog.get_default_response() == "cancel"
    assert dialog.get_close_response() == "cancel"


@pytest.mark.ui
def test_the_sheet_looks_like_the_cut_scale_sheet(ui_context_initializer):
    dialog, _on_cut, _on_pick = _dialog()

    assert dialog.has_css_class("sc-sheet")
    assert (
        dialog.get_response_appearance("cut")
        == Adw.ResponseAppearance.DESTRUCTIVE
    )
    assert dialog.get_response_label("cancel") == "Cancel"
    assert dialog.get_response_label("pick") == "Choose Spot…"
    assert dialog.get_response_label("cut") == "Cut"


@pytest.mark.ui
def test_it_says_what_it_cuts_and_that_the_head_returns(
    ui_context_initializer,
):
    """
    The layer, its speed in mm/s, its Max and Min Power, and that it
    is one pass, in one line.
    """
    dialog, _on_cut, _on_pick = _dialog()

    body = dialog.get_body()

    assert "Cut layer" in body
    assert "20.0 mm/s" in body
    assert "Max Power 45%" in body
    assert "Min Power 30%" in body
    assert "one pass" in body
    assert "10 mm" in body
    assert "head returns" in body
    assert "\n" not in body
