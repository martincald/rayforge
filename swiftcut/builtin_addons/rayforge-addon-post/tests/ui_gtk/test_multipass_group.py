# flake8: noqa: E402
"""UI tests: the multi-pass group sets the number of passes only.

The Ruida encoder has no Z axis, so there is no Z step-down row; the
transformer keeps its z_step_down field so saved steps still load.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from gi.repository import Adw
from post_processors.transformers import MultiPassTransformer
from post_processors.widgets.multipass_group import MultiPassSettingsGroup


class _Page:
    use_expanders = True


@pytest.mark.ui
def test_multipass_group_offers_passes_only(ui_context):
    transformer = MultiPassTransformer(passes=3, z_step_down=0.5)
    group = MultiPassSettingsGroup("Multi-Pass", transformer, _Page())

    # With expanders the host page reparents the rows, so they are
    # read from the group's own list.
    titles = [
        row.get_title()
        for row in group._rows
        if isinstance(row, Adw.PreferencesRow)
    ]
    assert "Number of Passes" in titles
    assert not any("Z Step" in title for title in titles)
    assert transformer.to_dict()["z_step_down"] == 0.5
