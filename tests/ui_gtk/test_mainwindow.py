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
def test_start_is_disabled_while_a_job_runs(app_and_window):
    """Both Starts, toolbar and panel, follow MachineCmd's job state."""
    _app, win = app_and_window
    jog = win.bottom_panel.jog_widget
    machine = jog.machine
    send = win.action_manager.get_action("machine-send")

    with (
        _connected(machine, has_ops=True),
        patch.object(
            MachineCmd,
            "is_job_running",
            new_callable=PropertyMock,
            return_value=True,
        ),
    ):
        win.machine_cmd.job_state_changed.send(win.machine_cmd)

        assert not send.get_enabled()
        assert win.toolbar.send_button.get_tooltip_text() == "Job running"
        assert not jog.start_btn.get_sensitive()
        assert jog.start_btn.get_tooltip_text() == "Job running"

    with _connected(machine, has_ops=True):
        win.machine_cmd.job_state_changed.send(win.machine_cmd)

        assert win.toolbar.send_button.get_tooltip_text() != "Job running"
        assert jog.start_btn.get_sensitive()
        assert jog.start_btn.get_tooltip_text() == "Start job"


@pytest.mark.ui
def test_both_starts_go_through_one_guarded_method(app_and_window):
    """The toolbar's Send and the panel's Start reach run_send_job."""
    _app, win = app_and_window
    jog = win.bottom_panel.jog_widget
    machine = get_context().config.machine
    assert jog.machine is machine

    with (
        patch.object(
            win,
            "_run_sanity_check_and_proceed",
            side_effect=lambda proceed: proceed(),
        ),
        patch.object(win.machine_cmd, "run_send_job") as run_send_job,
    ):
        win.on_send_clicked(None, None)
        jog.start_btn.emit("clicked")

    assert [c.args for c in run_send_job.call_args_list] == [
        (machine,),
        (machine,),
    ]


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


# Focus Z runs from the dock's Laser tab, which offers nothing else.


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


def _submenu(menu, label: str):
    """The submenu of a top-level menu entry, by its label."""
    for i in range(menu.get_n_items()):
        title = menu.get_item_attribute_value(
            i, "label", GLib.VariantType.new("s")
        )
        if title is not None and title.get_string() == label:
            return menu.get_item_link(i, "submenu")
    raise AssertionError(f"no {label} menu")


@pytest.mark.ui
def test_machine_menu_offers_only_what_ruida_runs(app_and_window):
    """No macros, no clear alarm: the Ruida driver runs neither."""
    _app, win = app_and_window

    machine_menu = _submenu(win.menu_model, "_Machine")
    entries = [
        a for a in _menu_actions(machine_menu) if a.startswith("win.machine")
    ]

    assert entries == [
        "win.machine-home",
        "win.machine-frame",
        "win.machine-send",
        "win.machine-hold",
        "win.machine-cancel",
        "win.machine-settings",
    ]


@pytest.mark.ui
def test_export_means_the_ruida_job(app_and_window):
    """The File menu, the toolbar's export button and the primary+E
    shortcut all export the .rd job; there is no G-code export."""
    from swiftcut.ui_gtk.actions import SHORTCUTS
    from swiftcut.ui_gtk.shared.keyboard import PRIMARY_ACCEL

    _app, win = app_and_window

    file_menu = _submenu(win.menu_model, "_File")
    entries = [
        a
        for a in _menu_actions(file_menu)
        if not a.startswith("win.open-recent")
    ]
    assert entries == [
        "win.new",
        "win.open",
        "win.save",
        "win.save-as",
        "win.import",
        "win.export-rd",
        "win.export_document",
        "win.quit",
    ]
    assert win.toolbar.export_button.get_action_name() == "win.export-rd"
    assert win.toolbar.export_button.get_tooltip_text() == (
        "Export Ruida job (.rd)"
    )
    assert [
        name
        for name, accel in SHORTCUTS.items()
        if accel == f"{PRIMARY_ACCEL}e"
    ] == ["win.export-rd"]


@pytest.mark.ui
def test_laser_tab_holds_only_focus_z(app_and_window):
    """No pulse controls: the Ruida driver cannot fire a pulse."""
    _app, win = app_and_window
    laser = win.bottom_panel.laser_control

    rows = []
    child = laser._group.get_first_child()
    stack = [child] if child is not None else []
    while stack:
        widget = stack.pop()
        if isinstance(widget, Adw.PreferencesRow):
            rows.append(widget.get_title())
        nxt = widget.get_next_sibling()
        if nxt is not None:
            stack.append(nxt)
        inner = widget.get_first_child()
        if inner is not None:
            stack.append(inner)

    assert rows == ["Focus Z"]


@pytest.mark.ui
def test_console_is_a_log_with_no_command_line(app_and_window):
    """RuidaDriver.run_raw sends nothing, so there is nothing to type."""
    _app, win = app_and_window
    console = win.bottom_panel.console

    editable = []
    stack = [console.get_first_child()]
    while stack:
        widget = stack.pop()
        if widget is None:
            continue
        if isinstance(widget, Gtk.TextView) and widget.get_editable():
            editable.append(widget)
        stack.append(widget.get_next_sibling())
        stack.append(widget.get_first_child())

    assert editable == []
    assert not console.terminal.get_editable()


@pytest.mark.ui
def test_zero_axes_row_has_no_z(app_and_window):
    """The Ruida driver ignores a Z work offset."""
    _app, win = app_and_window
    panel = win.bottom_panel

    labels = []
    stack = [panel.zero_row.get_first_child()]
    while stack:
        widget = stack.pop()
        if widget is None:
            continue
        if isinstance(widget, Gtk.Button) and widget.get_label():
            labels.append(widget.get_label())
        stack.append(widget.get_next_sibling())
        stack.append(widget.get_first_child())

    assert "X" in labels and "Y" in labels
    assert "Z" not in labels


@pytest.mark.ui
def test_help_menu_has_no_donate_entry(app_and_window):
    _app, win = app_and_window

    actions = _menu_actions(win.menu_model)
    assert "win.about" in actions
    assert "win.donate" not in actions

    assert win.lookup_action("about") is not None
    assert win.lookup_action("donate") is None
