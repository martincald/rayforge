"""The first-run guide: three cards (connect, open or draw, Go Scale
then Start), shown once on the first launch and again only from Help.

App.do_activate opens it through MainWindow.maybe_show_getting_started
as the window maps; swiftcut.app is never imported in tests (it has
import-time side effects), so these tests drive that method.
"""

import time
from unittest.mock import MagicMock, PropertyMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from swiftcut.context import get_context  # noqa: E402
from swiftcut.machine.models.machine import Machine  # noqa: E402
from swiftcut.machine.transport.transport import (  # noqa: E402
    TRANSPORT_STATUS_LABELS,
    TransportStatus,
)


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def _open_guides():
    from swiftcut.ui_gtk.getting_started import GettingStartedWindow

    return [
        window
        for window in Gtk.Window.list_toplevels()
        if isinstance(window, GettingStartedWindow) and window.get_visible()
    ]


@pytest.fixture
def main_window(ui_context_initializer):
    from swiftcut.ui_gtk.mainwindow import MainWindow

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    app = App(application_id="org.swiftcut.swiftcut.test.getting-started")
    app.register(None)
    app.activate()
    win = app.win
    win.present()
    _pump(0.3)
    yield win
    for guide in _open_guides():
        guide.destroy()
    win.doc_editor.cleanup()
    win.destroy()
    app.quit()
    _pump(0.2)


@pytest.fixture
def guide(ui_context_initializer):
    from swiftcut.ui_gtk.getting_started import GettingStartedWindow

    window = GettingStartedWindow()
    yield window
    window.destroy()


@pytest.mark.ui
def test_shown_on_a_fresh_config_but_never_in_a_scripted_run(
    ui_context_initializer,
):
    from swiftcut.ui_gtk.getting_started import should_show_getting_started

    config = get_context().config
    assert config.getting_started_seen is False

    assert should_show_getting_started(config, scripted=False)
    # --uiscript and --exit runs.
    assert not should_show_getting_started(config, scripted=True)

    get_context().exit_after_settle = True
    try:
        assert not should_show_getting_started(config, scripted=False)
    finally:
        get_context().exit_after_settle = False

    config.set_getting_started_seen(True)
    assert not should_show_getting_started(config, scripted=False)


@pytest.mark.ui
def test_the_guide_opens_once_then_never_again(main_window):
    win = main_window
    config = get_context().config

    win.maybe_show_getting_started(scripted=False)
    _pump(0.1)
    (guide,) = _open_guides()
    assert guide.get_transient_for() is win
    assert config.getting_started_seen is False

    guide.close()
    _pump(0.1)

    assert config.getting_started_seen is True
    win.maybe_show_getting_started(scripted=False)
    _pump(0.1)
    assert _open_guides() == []


@pytest.mark.ui
def test_no_guide_in_a_scripted_run(main_window):
    main_window.maybe_show_getting_started(scripted=True)
    _pump(0.1)

    assert _open_guides() == []
    assert get_context().config.getting_started_seen is False


@pytest.mark.ui
def test_help_reopens_the_guide_even_once_seen(main_window):
    from swiftcut.ui_gtk.getting_started import GettingStartedWindow

    win = main_window
    get_context().config.set_getting_started_seen(True)

    help_menu = None
    for i in range(win.menu_model.get_n_items()):
        label = win.menu_model.get_item_attribute_value(i, "label", None)
        if label is not None and label.get_string() == "_Help":
            help_menu = win.menu_model.get_item_link(i, "submenu")
    assert help_menu is not None
    actions = [
        help_menu.get_item_attribute_value(i, "action", None).get_string()
        for i in range(help_menu.get_n_items())
    ]
    assert "win.getting-started" in actions

    win.activate_action("win.getting-started", None)
    _pump(0.1)

    (guide,) = _open_guides()
    assert isinstance(guide, GettingStartedWindow)
    # Asking again brings the open guide forward rather than a second.
    win.activate_action("win.getting-started", None)
    _pump(0.1)
    assert _open_guides() == [guide]


@pytest.mark.ui
def test_got_it_closes_the_guide_and_marks_it_seen(main_window):
    main_window.show_getting_started(None, None)
    _pump(0.1)
    (guide,) = _open_guides()
    got_it = [
        w for w in _descendants(guide)
        if isinstance(w, Gtk.Button) and w.get_label() == "Got It"
    ]

    got_it[0].emit("clicked")
    _pump(0.1)

    assert _open_guides() == []
    assert get_context().config.getting_started_seen is True


@pytest.mark.ui
def test_open_imports_a_drawing_into_the_main_window(main_window):
    win = main_window
    imported = []
    win.action_manager.get_action("import").connect(
        "activate", lambda action, param: imported.append(param)
    )
    win.show_getting_started(None, None)
    _pump(0.1)
    (guide,) = _open_guides()

    with patch.object(win, "on_menu_import"):
        guide.open_button.emit("clicked")

    assert imported == [None]


def _descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


@pytest.mark.ui
def test_the_three_cards_say_what_to_do(guide):
    cards = [w for w in _descendants(guide) if w.has_css_class("card")]
    titles = [
        label.get_label()
        for card in cards
        for label in _descendants(card)
        if isinstance(label, Gtk.Label) and label.has_css_class("sc-title")
    ]

    assert titles == [
        "1. Connect by USB",
        "2. Open or draw something",
        "3. Press Go Scale, then Start",
    ]
    assert guide.connection_status in _descendants(cards[0])
    assert guide.open_button in _descendants(cards[1])
    texts = [
        w.get_label() for w in _descendants(cards[1])
        if isinstance(w, Gtk.Label)
    ]
    assert any("Object > New Sketch" in text for text in texts)


@pytest.mark.ui
def test_card_one_follows_the_live_connection_state(guide):
    machine = get_context().config.machine
    status = guide.connection_status
    assert status.machine is machine

    # The seeded test machine has no device driver, which always reads
    # "Disconnected"; a real driver shows what the transport reports.
    with patch.object(
        type(machine), "driver", new_callable=PropertyMock,
        return_value=MagicMock(),
    ):
        for state in (
            TransportStatus.CONNECTING,
            TransportStatus.CONNECTED,
            TransportStatus.ERROR,
        ):
            machine.connection_status_changed.send(machine, status=state)
            assert status.label.get_label() == (
                TRANSPORT_STATUS_LABELS[state]
            )


@pytest.mark.ui
def test_card_one_follows_a_machine_switch_until_closed(
    guide, ui_context_initializer
):
    config = get_context().config
    first = config.machine
    other = Machine(ui_context_initializer)
    other.name = "ilab-626"
    ui_context_initializer.machine_mgr.add_machine(other)

    config.set_machine(other)
    assert guide.connection_status.machine is other

    # Only a window on screen can be closed.
    guide.present()
    _pump(0.1)
    guide.close()
    assert guide.connection_status.machine is None
    config.set_machine(first)
    assert guide.connection_status.machine is None
