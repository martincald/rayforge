# flake8: noqa: E402
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

# Platform-Specific Setup
if sys.platform.startswith("linux"):
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    if not os.environ.get("DISPLAY"):
        pytest.skip(
            "DISPLAY not set on Linux, skipping UI tests. Run with xvfb-run.",
            allow_module_level=True,
        )


# Gtk imports must happen AFTER the platform setup and display check.
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, GLib, Gtk

from swiftcut.context import get_context
from swiftcut.machine.cmd import MachineCmd
from swiftcut.machine.driver.driver import DeviceState, DeviceStatus
from swiftcut.machine.transport import TransportStatus
from swiftcut.ui_gtk.mainwindow import MainWindow

logger = logging.getLogger(__name__)


# Helper functions adapted for robust testing


def process_events_for_duration(duration_sec: float):
    """
    Processes all pending GTK events for a given duration without blocking.
    """
    end_time = time.monotonic() + duration_sec
    context = GLib.main_context_default()
    while time.monotonic() < end_time:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def wait_for_document_to_settle(window: MainWindow, timeout: int = 45) -> bool:
    """
    Waits for the 'document_settled' signal in a thread-safe manner.
    """
    settled_event = threading.Event()

    def on_settled(sender):
        logger.info("Received 'document_settled' signal.")
        settled_event.set()

    handler_id = window.doc_editor.document_settled.connect(on_settled)

    logger.info("Waiting for document to settle...")
    start_time = time.monotonic()

    while not settled_event.is_set():
        process_events_for_duration(0.1)
        if time.monotonic() - start_time > timeout:
            logger.error("Timeout waiting for document_settled signal.")
            window.doc_editor.document_settled.disconnect(handler_id)
            return False

    window.doc_editor.document_settled.disconnect(handler_id)
    return window.doc_editor.doc.has_result()


@pytest.fixture
def assets_path() -> Path:
    return Path(__file__).parent.parent


@pytest.fixture
def test_file_path(assets_path: Path) -> Path:
    path = assets_path / "image" / "png" / "color.png"
    assert path.exists()
    return path


@pytest.fixture
def app_and_window(ui_context_initializer, request):
    """Sets up the Adw.Application and MainWindow without blocking."""
    from swiftcut.ui_gtk.shared import model_preview

    model_preview.initialize()
    assert model_preview.initialized, "OpenGL model preview failed to init"

    win = None

    class TestApp(Adw.Application):
        def do_activate(self):
            nonlocal win
            win = MainWindow(application=self)
            win.set_default_size(1280, 800)
            self.win = win

    test_name = request.node.name.replace("_", "-")
    app_id = f"org.swiftcut.swiftcut.test.{test_name}"
    app = TestApp(application_id=app_id)
    app.register(None)
    app.activate()
    process_events_for_duration(0.5)

    assert hasattr(app, "win") and app.win is not None
    win = app.win
    win.present()
    process_events_for_duration(0.5)

    yield app, win

    # Teardown
    if win:
        win.doc_editor.cleanup()
        win.close()
        app.quit()
    process_events_for_duration(0.2)


# The toolbar's machine controls. Go Scale and Cut Scale press the jog
# panel's buttons, so the toolbar follows their state rather than
# deciding it again.


def _toolbar_action_names(toolbar) -> list[str]:
    """The action names of the toolbar's buttons, left to right."""
    names = []
    child = toolbar.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Actionable) and child.get_action_name():
            names.append(child.get_action_name())
        child = child.get_next_sibling()
    return names


def _icon_file(button) -> str:
    """The icon file an icon-only button shows."""
    image = button.get_child()
    assert isinstance(image, Gtk.Image)
    return image.get_gicon().get_file().get_basename()


@contextmanager
def _connected(machine, has_ops: bool):
    """Present the machine as connected, with or without job ops."""
    status = machine.connection_status
    machine.connection_status = TransportStatus.CONNECTED
    try:
        with (
            patch.object(type(machine), "is_connected", return_value=True),
            patch.object(
                MachineCmd,
                "has_job_ops",
                new_callable=PropertyMock,
                return_value=has_ops,
            ),
        ):
            yield
    finally:
        machine.connection_status = status


def _refresh(win: MainWindow):
    """Run the jog panel's state pass, then the window's."""
    win.bottom_panel.jog_widget._update_button_sensitivity()
    win._update_actions_and_ui()


@pytest.mark.ui
def test_toolbar_has_no_laser_pulse_button(app_and_window):
    _app, win = app_and_window

    assert not hasattr(win.toolbar, "focus_button")
    assert "win.toggle-focus" not in _toolbar_action_names(win.toolbar)


@pytest.mark.ui
def test_scale_buttons_take_the_frame_slot(app_and_window):
    _app, win = app_and_window

    names = _toolbar_action_names(win.toolbar)

    assert names[names.index("win.machine-home") :] == [
        "win.machine-home",
        "win.machine-go-scale",
        "win.machine-cut-scale",
        "win.machine-send",
        "win.machine-hold",
        "win.machine-cancel",
        "win.machine-clear-alarm",
    ]
    # Frame keeps its action for the Machine menu.
    assert win.action_manager.get_action("machine-frame") is not None


@pytest.mark.ui
def test_toolbar_control_icons(app_and_window):
    """
    Go Scale and Cut Scale are icon-only, with the jog panel's glyphs;
    Home, Start, Pause and Stop keep theirs.
    """
    _app, win = app_and_window
    toolbar = win.toolbar

    assert _icon_file(toolbar.home_button) == "home-symbolic.svg"
    assert _icon_file(toolbar.go_scale_button) == "frame-symbolic.svg"
    assert _icon_file(toolbar.cut_scale_button) == "laser-on-symbolic.svg"
    assert _icon_file(toolbar.send_button) == "send-symbolic.svg"
    assert _icon_file(toolbar.hold_button) == "pause-symbolic.svg"
    assert _icon_file(toolbar.cancel_button) == "stop-symbolic.svg"


@pytest.mark.ui
def test_scale_actions_say_why_they_are_disabled(app_and_window):
    _app, win = app_and_window
    am = win.action_manager
    toolbar = win.toolbar
    machine = win.bottom_panel.jog_widget.machine
    assert machine is not None

    assert not am.get_action("machine-go-scale").get_enabled()
    assert not am.get_action("machine-cut-scale").get_enabled()
    assert not toolbar.go_scale_button.get_sensitive()
    assert not toolbar.cut_scale_button.get_sensitive()
    assert toolbar.go_scale_button.get_tooltip_text() == (
        "Go Scale: connect to the machine first"
    )
    assert toolbar.cut_scale_button.get_tooltip_text() == (
        "Cut Scale: connect to the machine first"
    )

    # The panel buttons stay insensitive here; only the reason moves.
    with _connected(machine, has_ops=False):
        _refresh(win)

        assert not am.get_action("machine-go-scale").get_enabled()
        assert not am.get_action("machine-cut-scale").get_enabled()
        assert toolbar.go_scale_button.get_tooltip_text() == (
            "Go Scale: the job has no operations"
        )
        assert toolbar.cut_scale_button.get_tooltip_text() == (
            "Cut Scale: the job has no operations"
        )

    # A panel that has not caught up yet is not a running scale.
    with _connected(machine, has_ops=True):
        win._update_scale_actions()

        assert not am.get_action("machine-go-scale").get_enabled()
        assert toolbar.go_scale_button.get_tooltip_text() == (
            "Go Scale: not available right now"
        )
        assert toolbar.cut_scale_button.get_tooltip_text() == (
            "Cut Scale: not available right now"
        )


@pytest.mark.ui
def test_go_scale_action_runs_and_then_stops_the_panel_scale(
    app_and_window,
):
    _app, win = app_and_window
    am = win.action_manager
    toolbar = win.toolbar
    machine = win.bottom_panel.jog_widget.machine

    with (
        _connected(machine, has_ops=True),
        patch.object(win.machine_cmd, "run_go_scale") as run_go_scale,
        patch.object(win.machine_cmd, "cancel_job") as cancel_job,
    ):
        _refresh(win)
        assert am.get_action("machine-go-scale").get_enabled()
        assert am.get_action("machine-cut-scale").get_enabled()
        assert toolbar.go_scale_button.get_tooltip_text() == (
            "Traverse the job outline with the laser off"
        )
        assert toolbar.cut_scale_button.get_tooltip_text() == (
            "Cut a rectangle around the job outline"
        )

        toolbar.go_scale_button.emit("clicked")

        run_go_scale.assert_called_once()
        assert run_go_scale.call_args.args[0] is machine
        # While it runs, Go Scale is the panel's Stop.
        assert am.get_action("machine-go-scale").get_enabled()
        assert toolbar.go_scale_button.get_tooltip_text() == (
            "Stop the running scale"
        )
        assert not am.get_action("machine-cut-scale").get_enabled()
        assert toolbar.cut_scale_button.get_tooltip_text() == (
            "Cut Scale: a scale is already running"
        )

        toolbar.go_scale_button.emit("clicked")

        cancel_job.assert_called_once_with(machine)
        assert run_go_scale.call_count == 1


@pytest.mark.ui
def test_cut_scale_action_asks_for_confirmation_first(app_and_window):
    _app, win = app_and_window
    machine = win.bottom_panel.jog_widget.machine

    with (
        _connected(machine, has_ops=True),
        patch.object(win.machine_cmd, "run_cut_scale") as run_cut_scale,
        patch(
            "swiftcut.ui_gtk.machine.jog_widget.CutScaleDialog"
        ) as dialog_cls,
    ):
        _refresh(win)

        win.toolbar.cut_scale_button.emit("clicked")

        dialog_cls.return_value.present.assert_called_once()
        run_cut_scale.assert_not_called()

        confirm = dialog_cls.call_args.args[1]
        confirm(1200, 0.5)

        run_cut_scale.assert_called_once()
        assert run_cut_scale.call_args.args[:3] == (machine, 1200, 0.5)


@pytest.mark.ui
def test_both_stop_buttons_cancel_through_one_method(app_and_window):
    """The toolbar's Stop and the jog panel's reach one cancel_job."""
    _app, win = app_and_window
    jog = win.bottom_panel.jog_widget
    machine = jog.machine
    assert jog.machine_cmd is win.machine_cmd

    with (
        _connected(machine, has_ops=True),
        patch.object(win.machine_cmd, "cancel_job") as cancel_job,
    ):
        _refresh(win)
        assert win.action_manager.get_action("machine-cancel").get_enabled()

        win.toolbar.cancel_button.emit("clicked")
        jog.stop_btn.emit("clicked")

        assert cancel_job.call_args_list == [
            ((machine,),),
            ((machine,),),
        ]


# Focus Z runs from the dock's Laser tab; pulse and clear alarm are
# offered only by a driver that has a command for them.

UNSUPPORTED = "Not supported on this controller"


@pytest.mark.ui
def test_laser_tab_focus_runs_only_when_connected_and_idle(app_and_window):
    _app, win = app_and_window
    action = win.action_manager.get_action("machine-focus-z")
    laser = win.bottom_panel.laser_control
    focus = laser._focus_btn
    machine = laser.machine
    assert focus.get_action_name() == "win.machine-focus-z"

    with (
        patch.object(type(machine.driver), "can_focus_z", return_value=True),
        patch(
            "swiftcut.ui_gtk.mainwindow.task_mgr.has_tasks",
            return_value=False,
        ),
    ):
        win._update_actions_and_ui()
        assert not action.get_enabled()
        assert not focus.get_sensitive()

        idle = DeviceState(status=DeviceStatus.IDLE)
        with (
            _connected(machine, has_ops=False),
            patch.object(machine, "device_state", idle),
        ):
            win._update_actions_and_ui()
            assert action.get_enabled()
            assert focus.get_sensitive()

            with patch.object(
                MachineCmd,
                "is_job_running",
                new_callable=PropertyMock,
                return_value=True,
            ):
                win._update_actions_and_ui()
                assert not action.get_enabled()
                assert not focus.get_sensitive()

            win._update_actions_and_ui()
            with patch.object(win.machine_cmd, "focus_z") as focus_z:
                focus.emit("clicked")
            focus_z.assert_called_once_with(machine)


@pytest.mark.ui
def test_focus_z_turns_the_focus_laser_off_first(app_and_window):
    _app, win = app_and_window
    machine = win.bottom_panel.laser_control.machine
    head = machine.get_default_laser_head()
    toggle_focus = win.action_manager.get_action("toggle-focus")
    sent = MagicMock()

    with (
        patch.object(
            win.machine_cmd, "set_focus_power", sent.set_focus_power
        ),
        patch.object(win.machine_cmd, "focus_z", sent.focus_z),
    ):
        toggle_focus.set_state(GLib.Variant.new_boolean(True))
        win.on_focus_z_clicked(
            win.action_manager.get_action("machine-focus-z"), None
        )

    assert not toggle_focus.get_state().get_boolean()
    assert sent.mock_calls == [
        call.set_focus_power(head, 0),
        call.focus_z(machine),
    ]


@pytest.mark.ui
def test_laser_tab_focus_needs_a_driver_that_can_focus(app_and_window):
    _app, win = app_and_window
    machine = win.bottom_panel.laser_control.machine
    idle = DeviceState(status=DeviceStatus.IDLE)

    with (
        patch.object(type(machine.driver), "can_focus_z", return_value=False),
        _connected(machine, has_ops=False),
        patch.object(machine, "device_state", idle),
    ):
        win._update_actions_and_ui()

        assert not win.action_manager.get_action(
            "machine-focus-z"
        ).get_enabled()


@pytest.mark.ui
def test_laser_tab_pulse_says_it_is_not_supported(app_and_window):
    _app, win = app_and_window
    laser = win.bottom_panel.laser_control
    machine = laser.machine
    assert machine.heads
    pulse_rows = (laser._power_row, laser._duration_row)

    with _connected(machine, has_ops=False):
        with patch.object(
            type(machine.driver), "can_pulse", return_value=False
        ):
            laser._update_sensitivity()

            assert not laser._toggle_btn.get_sensitive()
            assert laser._toggle_btn.get_tooltip_text() == UNSUPPORTED
            for row in pulse_rows:
                assert not row.get_sensitive()
                assert row.get_tooltip_text() == UNSUPPORTED

        with patch.object(
            type(machine.driver), "can_pulse", return_value=True
        ):
            laser._update_sensitivity()

            assert laser._toggle_btn.get_sensitive()
            assert laser._toggle_btn.get_tooltip_text() == (
                "Toggle laser on/off"
            )
            for row in pulse_rows:
                assert row.get_sensitive()
                assert row.get_tooltip_text() is None


@pytest.mark.ui
def test_laser_tab_can_switch_off_a_laser_turned_on_elsewhere(
    app_and_window,
):
    """Print-and-Cut's focus toggle turns it on; off stays available."""
    _app, win = app_and_window
    laser = win.bottom_panel.laser_control
    machine = laser.machine
    head = machine.heads[0]
    controller = machine.controller

    with (
        _connected(machine, has_ops=False),
        patch.object(type(machine.driver), "can_pulse", return_value=False),
        patch.object(laser.machine_cmd, "set_focus_power") as set_power,
    ):
        controller.laser_power_changed.send(
            controller, head=head, percent=0.2
        )

        assert laser._toggle_btn.get_active()
        assert laser._toggle_btn.get_sensitive()

        laser._toggle_btn.emit("clicked")

        set_power.assert_called_once_with(head, 0, machine)
        assert not laser._toggle_btn.get_sensitive()
        assert laser._toggle_btn.get_tooltip_text() == UNSUPPORTED


@pytest.mark.ui
def test_laser_tab_survives_a_removed_machines_last_disconnect(
    app_and_window,
):
    """Its controller is gone by then, so the driver cannot be asked."""
    _app, win = app_and_window
    laser = win.bottom_panel.laser_control
    machine = laser.machine

    with (
        patch.object(
            type(machine),
            "has_controller",
            new_callable=PropertyMock,
            return_value=False,
        ),
        patch.object(
            type(machine),
            "driver",
            new_callable=PropertyMock,
            side_effect=ValueError("No machine found"),
        ),
    ):
        laser._update_sensitivity()

    assert not laser._toggle_btn.get_sensitive()


@pytest.mark.ui
def test_clear_alarm_says_it_is_not_supported(app_and_window):
    _app, win = app_and_window
    action = win.action_manager.get_action("machine-clear-alarm")
    button = win.toolbar.clear_alarm_button
    machine = win.bottom_panel.laser_control.machine
    alarm = DeviceState(status=DeviceStatus.ALARM)

    with patch.object(machine, "device_state", alarm):
        with patch.object(
            type(machine.driver), "can_clear_alarm", return_value=False
        ):
            win._update_actions_and_ui()

            assert not action.get_enabled()
            assert not button.get_sensitive()
            assert button.get_tooltip_text() == UNSUPPORTED

        with patch.object(
            type(machine.driver), "can_clear_alarm", return_value=True
        ):
            win._update_actions_and_ui()

            assert action.get_enabled()
            assert button.get_tooltip_text() == (
                "Clear machine alarm (unlock)"
            )

    # With no machine there is no controller to be unsupported.
    with patch.object(
        type(machine.driver), "can_clear_alarm", return_value=False
    ):
        win._update_actions_and_ui()
        with patch.object(get_context().config, "machine", None):
            win._update_actions_and_ui()

    assert not action.get_enabled()
    assert button.get_tooltip_text() == "Clear machine alarm (unlock)"


def _menu_actions(menu) -> list[str]:
    """Every action name in a menu model, including submenus/sections."""
    actions = []
    for i in range(menu.get_n_items()):
        action = menu.get_item_attribute_value(
            i, "action", GLib.VariantType.new("s")
        )
        if action is not None:
            actions.append(action.get_string())
        for link in ("submenu", "section"):
            child = menu.get_item_link(i, link)
            if child is not None:
                actions.extend(_menu_actions(child))
    return actions


@pytest.mark.ui
def test_help_menu_has_no_donate_entry(app_and_window):
    _app, win = app_and_window

    actions = _menu_actions(win.menu_model)
    assert "win.about" in actions
    assert "win.donate" not in actions

    assert win.lookup_action("about") is not None
    assert win.lookup_action("donate") is None
