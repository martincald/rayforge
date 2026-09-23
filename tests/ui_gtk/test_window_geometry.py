"""Where the main window opens and how big, per monitor.

A monitor the window has never been on gets the design size or 90% of
its work area, whichever is smaller; after that it gets back what it
had there.
"""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from gi.repository import Gdk

from swiftcut.core.config import Config
from swiftcut.ui_gtk import window_geometry
from swiftcut.ui_gtk.window_geometry import (
    capture,
    default_size,
    monitor_key,
    restore_size,
)


def _rect(width, height, x=0, y=0) -> Gdk.Rectangle:
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = x, y, width, height
    return rect


# A 13" MacBook Air: 1440x900 logical, less the menu bar and the Dock.
MACBOOK_13 = _rect(1440, 821, 0, 30)
# A 27" 1440p display, less the menu bar.
DISPLAY_27 = _rect(2560, 1415, 0, 25)


def test_a_13_inch_macbook_gets_90_percent_of_its_work_area():
    assert default_size(MACBOOK_13) == (1296, 738)


def test_a_27_inch_display_gets_the_design_size():
    assert default_size(DISPLAY_27) == window_geometry.DESIGN_SIZE


def test_the_default_always_fits_the_work_area():
    for workarea in (MACBOOK_13, DISPLAY_27, _rect(1024, 700)):
        width, height = default_size(workarea)
        assert width <= workarea.width and height <= workarea.height


def test_a_remembered_size_comes_back():
    assert restore_size({"width": 1180, "height": 700}, MACBOOK_13) == (
        1180,
        700,
    )


def test_a_remembered_size_never_exceeds_the_work_area():
    saved = {"width": 2400, "height": 1300}

    assert restore_size(saved, MACBOOK_13) == (1440, 821)


def test_a_maximized_only_entry_falls_back_to_the_default():
    assert restore_size({"maximized": True}, MACBOOK_13) == (1296, 738)


def test_nothing_remembered_is_the_default():
    assert restore_size(None, DISPLAY_27) == (1920, 1080)


def test_the_monitor_key_names_its_place_and_size():
    monitor = MagicMock()
    monitor.get_geometry.return_value = _rect(2560, 1440, 1440, -270)

    assert monitor_key(monitor) == "2560x1440+1440+-270"


def _window(maximized: bool, width=1180, height=700):
    monitor = MagicMock()
    monitor.get_geometry.return_value = _rect(1440, 900)
    window = MagicMock()
    window.is_maximized.return_value = maximized
    window.get_width.return_value = width
    window.get_height.return_value = height
    window.get_display.return_value.get_monitor_at_surface.return_value = (
        monitor
    )
    return window


def test_capture_keys_the_size_by_monitor(monkeypatch):
    monkeypatch.setattr(window_geometry, "window_position", lambda w: None)

    captured = capture(_window(maximized=False))
    assert captured is not None
    key, state = captured

    assert key == "1440x900+0+0"
    assert state == {"maximized": False, "width": 1180, "height": 700}


def test_capture_of_a_maximized_window_keeps_the_last_size(monkeypatch):
    """The size to go back to on unmaximize is not the screen's."""
    monkeypatch.setattr(
        window_geometry, "window_position", lambda w: (72.0, 91.0)
    )
    config = Config()
    config.set_window_geometry(
        "1440x900+0+0", {"width": 1180, "height": 700, "maximized": False}
    )

    captured = capture(_window(maximized=True))
    assert captured is not None
    config.set_window_geometry(*captured)

    assert config.window_geometry["1440x900+0+0"] == {
        "width": 1180,
        "height": 700,
        "maximized": True,
        "x": 72.0,
        "y": 91.0,
    }


def test_the_geometry_survives_the_config_file():
    config = Config()
    config.set_window_geometry(
        "1440x900+0+0", {"width": 1180, "height": 700, "maximized": False}
    )
    config.set_window_geometry("2560x1440+1440+0", {"maximized": True})

    restored = Config.from_dict(config.to_dict(), lambda _id: None)

    assert restored.window_geometry == config.window_geometry


def test_a_config_without_it_starts_empty():
    restored = Config.from_dict({}, lambda _id: None)

    assert restored.window_geometry == {}


def test_each_monitor_keeps_its_own_size():
    config = Config()
    config.set_window_geometry("1440x900+0+0", {"width": 1180})
    config.set_window_geometry("2560x1440+1440+0", {"width": 2200})

    assert config.window_geometry["1440x900+0+0"]["width"] == 1180
    assert config.window_geometry["2560x1440+1440+0"]["width"] == 2200


@pytest.mark.parametrize("preference", [True, False])
def test_narrow_collapses_the_sidebar_and_wide_restores_it(
    monkeypatch, preference
):
    from gi.repository import Gio, GLib

    from swiftcut.ui_gtk.mainwindow import MainWindow

    config = Config()
    config.right_panel_visible = preference
    monkeypatch.setattr(
        "swiftcut.ui_gtk.mainwindow.get_context",
        lambda: SimpleNamespace(config=config),
    )
    action = Gio.SimpleAction.new_stateful(
        "toggle_right_panel", None, GLib.Variant.new_boolean(preference)
    )
    pane = MagicMock()
    host = cast(
        Any, SimpleNamespace(_right_pane=pane, lookup_action=lambda n: action)
    )

    def shown() -> bool:
        state = action.get_state()
        assert state is not None
        return state.get_boolean()

    MainWindow._on_narrow_changed(host, None, True)
    assert pane.set_visible.call_args.args == (False,)
    assert shown() is False

    MainWindow._on_narrow_changed(host, None, False)
    assert pane.set_visible.call_args.args == (preference,)
    assert shown() is preference
    # Collapsing is a view change, never a change of preference.
    assert config.right_panel_visible is preference
