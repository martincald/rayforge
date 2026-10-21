"""The three guided tours, Help > Tours, and 'Your first cut' after the
first-run guide.

Every step is walked in a fresh window. The steps that wait for the
user are moved on through the model, as the user's action would; no
step sends the machine anything: a connected machine is faked, and
every command the jog panel could send is stubbed.
"""

import time
from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Graphene, Gtk  # noqa: E402

from swiftcut.context import get_context  # noqa: E402
from swiftcut.core.config import TOUR_COMPLETED, TOUR_SEEN  # noqa: E402
from swiftcut.core.group import Group  # noqa: E402
from swiftcut.core.workpiece import WorkPiece  # noqa: E402
from swiftcut.machine.models.machine import StartCorner  # noqa: E402
from swiftcut.machine.transport.transport import (  # noqa: E402
    TransportStatus,
)
from swiftcut.ui_gtk.machine.cut_scale_dialog import (  # noqa: E402
    CutScaleDialog,
)
from swiftcut.ui_gtk.machine.start_position_dialog import (  # noqa: E402
    start_chosen,
)
from swiftcut.ui_gtk.tour import overlay  # noqa: E402
from swiftcut.ui_gtk.tour.content import (  # noqa: E402
    FIRST_CUT,
    LAYERS,
    POSITIONING,
    TOURS,
)
from swiftcut.ui_gtk.tour.dialog import ToursWindow  # noqa: E402
from swiftcut.ui_gtk.tour.runner import TourRunner  # noqa: E402

# The controls that are off until the laser is connected and the
# design has something to cut.
MACHINE_ONLY = {"jog.home", "jog.go-scale", "jog.cut-scale", "jog.start"}


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def _windows(cls) -> list:
    return [
        window
        for window in Gtk.Window.list_toplevels()
        if isinstance(window, cls) and window.get_visible()
    ]


@pytest.fixture
def main_window(ui_context_initializer):
    from swiftcut.ui_gtk.getting_started import GettingStartedWindow
    from swiftcut.ui_gtk.mainwindow import MainWindow

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    app = App(application_id="org.swiftcut.swiftcut.test.tour-content")
    app.register(None)
    app.activate()
    win = app.win
    win.present()
    _pump(0.3)
    yield win
    for window in _windows(GettingStartedWindow) + _windows(ToursWindow):
        window.destroy()
    win.doc_editor.cleanup()
    win.destroy()
    assert win.tour is None
    app.quit()
    _pump(0.2)


def _set_status(machine, status: TransportStatus):
    """What the controller does as the driver reports a new state."""
    machine.set_connection_status(status)
    machine.connection_status_changed.send(machine, status=status)


@contextmanager
def _fake_driver(win):
    """A machine that can read as connected, and sends nothing."""
    machine = get_context().config.machine
    cmd = win.machine_cmd
    driver = MagicMock()
    # A driver in good health: the toolbar shows a driver's error.
    driver.state.error = None
    with (
        patch.object(
            type(machine),
            "driver",
            new_callable=PropertyMock,
            return_value=driver,
        ),
        patch.object(
            type(cmd),
            "has_job_ops",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch.object(cmd, "set_jog_speed"),
        patch.object(cmd, "home"),
        patch.object(cmd, "cancel_job"),
        patch.object(cmd, "run_go_scale"),
        patch.object(cmd, "run_cut_scale"),
        patch.object(cmd, "run_send_job"),
        patch.object(cmd, "set_hold"),
        patch.object(cmd, "release_all_jog_keys"),
    ):
        try:
            yield machine
        finally:
            _set_status(machine, TransportStatus.DISCONNECTED)
            _pump(0.1)


@pytest.fixture
def connected(main_window):
    with _fake_driver(main_window) as machine:
        _set_status(machine, TransportStatus.CONNECTED)
        _pump(0.1)
        yield machine


def _play(win, tour) -> TourRunner:
    runner = TourRunner(win, tour)
    runner.start()
    _pump(0.3)
    return runner


def _walk(runner: TourRunner) -> dict[str, bool]:
    """Every step in turn: whether it has a hole, by target."""
    holes = {}
    for index in range(len(runner.tour.steps)):
        if index:
            runner.next()
            _pump(0.3)
        step = runner.step
        bubble = runner.bubble
        assert bubble.get_visible(), step.heading
        assert bubble.next_button.is_sensitive(), step.heading
        if runner.mask.hole is None:
            # A centred bubble that says why, never a step that sticks.
            assert step.target is None or bubble.reason.get_visible()
        else:
            assert not bubble.reason.get_visible(), step.heading
        holes[step.target] = runner.mask.hole is not None
    return holes


def _advances(runner: TourRunner, act) -> bool:
    index = runner.index
    act()
    _pump(0.2)
    return runner.index != index or not runner.active


# --- Every step ---------------------------------------------------------


@pytest.mark.ui
@pytest.mark.parametrize("tour_id", sorted(TOURS))
def test_every_step_points_at_its_control_or_says_why_not(
    main_window, tour_id
):
    runner = _play(main_window, TOURS[tour_id])

    holes = _walk(runner)

    # With no laser connected only the machine's own controls are off.
    assert {
        target for target, hole in holes.items() if not hole
    } == MACHINE_ONLY & set(holes)


@pytest.mark.ui
@pytest.mark.parametrize("tour_id", sorted(TOURS))
def test_with_the_laser_connected_every_step_has_its_hole(
    main_window, connected, tour_id
):
    runner = _play(main_window, TOURS[tour_id])

    holes = _walk(runner)

    assert all(holes.values()), holes


@pytest.mark.ui
@pytest.mark.parametrize("placement", ["beside", "in-the-middle"])
@pytest.mark.parametrize("tour_id", sorted(TOURS))
def test_no_bubble_lies_over_stop_or_pause(
    main_window, connected, tour_id, placement, monkeypatch
):
    middle = placement == "in-the-middle"
    if middle:
        # No bubble has room for its arrow: each one that would stand
        # beside its hole goes to the window's middle instead.
        monkeypatch.setattr(overlay, "_ARROW_ROOM", 1000)
    win = main_window
    jog = win.bottom_panel.jog_widget
    toolbar = win.toolbar
    # Go Scale while it is the Stop of a running scale is not among
    # them: on its own step it is the hole, and the popup's shadow
    # reaches into the hole on the arrow's side.
    buttons = (
        jog.stop_btn,
        jog.pause_btn,
        toolbar.cancel_button,
        toolbar.hold_button,
    )
    runner = _play(win, TOURS[tour_id])
    reached = set()

    for index in range(len(runner.tour.steps)):
        if index:
            runner.next()
            _pump(0.3)
        if middle:
            assert not runner.bubble.get_has_arrow(), runner.step.target
        popup = _popup_in_overlay(win, runner.bubble)
        for button in buttons:
            if not button.get_mapped():
                continue
            where = (runner.step.target, button)
            # The popup, shadow and all, lies off the button, and a
            # click at its middle passes the bubble by.
            assert not _overlap(popup, _bounds(button, win.tour_overlay)), (
                where
            )
            x, y = _center(button, win.tour_overlay)
            assert _bubble_pick(win, runner.bubble, x, y) is None, where
            # The toolbar's Pause is off until a job runs.
            if button.is_sensitive():
                hit = win.tour_overlay.pick(x, y, Gtk.PickFlags.DEFAULT)
                assert _is_within(hit, button), where
                reached.add(button)

    assert {jog.stop_btn, jog.pause_btn, toolbar.cancel_button} <= reached


def _bounds(widget, reference) -> tuple[float, float, float, float]:
    ok, bounds = widget.compute_bounds(reference)
    assert ok
    return (
        bounds.get_x(),
        bounds.get_y(),
        bounds.get_width(),
        bounds.get_height(),
    )


def _center(widget, reference) -> tuple[float, float]:
    x, y, width, height = _bounds(widget, reference)
    return x + width / 2, y + height / 2


def _overlap(a, b) -> bool:
    return (
        a[0] < b[0] + b[2]
        and b[0] < a[0] + a[2]
        and a[1] < b[1] + b[3]
        and b[1] < a[1] + a[3]
    )


def _is_within(widget, ancestor) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.get_parent()
    return False


def _popup_origin(win, bubble) -> tuple[float, float]:
    """Where the bubble's popup starts, in the tour overlay."""
    popup = bubble.get_surface()
    win_x, win_y = win.get_surface_transform()
    ok, origin = win.tour_overlay.compute_point(
        win, Graphene.Point().init(0, 0)
    )
    assert ok
    return (
        popup.get_position_x() - win_x - origin.x,
        popup.get_position_y() - win_y - origin.y,
    )


def _popup_in_overlay(win, bubble) -> tuple[float, float, float, float]:
    """The bubble's whole popup, shadow and all, in the tour overlay."""
    x, y = _popup_origin(win, bubble)
    popup = bubble.get_surface()
    return x, y, popup.get_width(), popup.get_height()


def _bubble_pick(win, bubble, x: float, y: float):
    """What, in the bubble, a click at x, y in the tour overlay hits."""
    popup_x, popup_y = _popup_origin(win, bubble)
    bubble_x, bubble_y = bubble.get_surface_transform()
    return bubble.pick(
        x - popup_x - bubble_x, y - popup_y - bubble_y, Gtk.PickFlags.DEFAULT
    )


def test_every_step_says_it_in_one_or_two_sentences():
    for tour in TOURS.values():
        assert tour.title and tour.steps
        for step in tour.steps:
            assert step.heading and step.body.endswith("."), step.body
            assert step.body.count(". ") + 1 <= 2, step.body


# --- Steps that move on -------------------------------------------------


@pytest.mark.ui
def test_your_first_cut_moves_on_as_the_user_does_each_step(main_window):
    win = main_window
    doc = win.doc_editor.doc
    config = get_context().config
    with _fake_driver(win) as machine:
        runner = _play(win, FIRST_CUT)

        assert runner.step.target == "jog.pad"
        assert not _advances(
            runner, lambda: _set_status(machine, TransportStatus.CONNECTING)
        )
        assert _advances(
            runner, lambda: _set_status(machine, TransportStatus.CONNECTED)
        )

        # Open or draw: another layer is not a shape; a workpiece is.
        assert runner.step.target == "canvas"
        assert not _advances(
            runner, win.doc_editor.layer.add_layer_and_set_active
        )
        assert _advances(
            runner, lambda: doc.active_layer.add_child(WorkPiece(name="sq"))
        )

        # The layer card waits for nothing.
        assert runner.step.target == "layers.active-card"
        runner.next()
        _pump(0.2)

        # Manual is no material; one is.
        assert runner.step.target == "layers.active-material"
        layer = doc.active_layer
        assert not _advances(runner, lambda: layer.set_color("#ff0000"))
        assert _advances(runner, lambda: layer.set_material(("mdf", 3.0)))

        assert runner.step.target == "dock.start-corner"
        corner = (
            StartCorner.BOTTOM_RIGHT
            if machine.start_corner != StartCorner.BOTTOM_RIGHT
            else StartCorner.TOP_LEFT
        )
        assert _advances(runner, lambda: machine.set_start_corner(corner))

        # Go Scale says what it does; Next goes on.
        assert runner.step.target == "jog.go-scale"
        runner.next()
        _pump(0.2)

        assert runner.step.target == "jog.start"
        assert _advances(
            runner, lambda: start_chosen.send(win, machine=machine)
        )
        assert win.tour is None
        assert config.tours[FIRST_CUT.id] == TOUR_COMPLETED


@pytest.mark.ui
def test_layers_moves_on_for_a_shape_moved_and_a_step_switched(main_window):
    win = main_window
    doc = win.doc_editor.doc
    # The first layer, with the steps a new document has, stays the
    # active one; a second layer, with none, is where shapes go.
    first = doc.active_layer
    shape = first.add_child(WorkPiece(name="square"))
    group = first.add_child(Group())
    grouped = group.add_child(WorkPiece(name="circle"))
    win.doc_editor.layer.add_layer_and_set_active()
    second = doc.active_layer
    win.doc_editor.layer.set_active_layer(first)
    _pump(0.2)
    runner = _play(win, LAYERS)
    runner.next()
    _pump(0.3)
    assert runner.step.target == "layers.tab" and runner.index == 1

    # A new shape is not a move, and nor is one taken out of a group.
    assert not _advances(
        runner, lambda: second.add_child(WorkPiece(name="triangle"))
    )
    assert not _advances(runner, lambda: first.add_child(grouped))
    assert _advances(
        runner,
        lambda: win.doc_editor.layer.move_items_to_layer([shape], second),
    )
    assert shape.layer is second

    # Switched off is not yet back as it was; switched on again is.
    assert runner.step.target == "pane.step-switch"
    assert runner.mask.hole is not None
    step = first.workflow.steps[0]
    assert not _advances(runner, lambda: step.set_visible(False))
    assert _advances(runner, lambda: step.set_visible(True))
    assert runner.step.target == "layers.active-eye"


@pytest.mark.ui
def test_positioning_moves_on_for_a_jog_home_corner_and_cut_scale(
    main_window, connected
):
    win = main_window
    machine = connected
    jog = win.bottom_panel.jog_widget
    runner = _play(win, POSITIONING)

    # A jog arrow's click, after its hold; the command is stubbed.
    assert runner.step.target == "jog.pad"
    assert _advances(runner, lambda: jog.north_btn.emit("clicked"))

    assert runner.step.target == "jog.home"
    assert _advances(runner, lambda: jog.home_all_btn.emit("clicked"))
    win.machine_cmd.home.assert_called_once()

    assert runner.step.target == "dock.start-corner"
    corner = (
        StartCorner.TOP_RIGHT
        if machine.start_corner != StartCorner.TOP_RIGHT
        else StartCorner.TOP_LEFT
    )
    assert _advances(runner, lambda: machine.set_start_corner(corner))

    # Cut Scale moves on, and ends the tour, as its question appears;
    # another window, such as Help > Tours, does not.
    assert runner.step.target == "jog.cut-scale"
    tours = ToursWindow(win)
    _pump(0.1)
    assert runner.active and runner.step.target == "jog.cut-scale"
    tours.destroy()
    dialog = CutScaleDialog(50.0, lambda speed, power: None)
    try:
        _pump(0.2)
        assert win.tour is None
        assert get_context().config.tours[POSITIONING.id] == TOUR_COMPLETED
    finally:
        dialog.destroy()
    win.machine_cmd.run_cut_scale.assert_not_called()


# --- Help > Tours -------------------------------------------------------


def _help_actions(win) -> list[str]:
    menu = win.menu_model
    for i in range(menu.get_n_items()):
        label = menu.get_item_attribute_value(i, "label", None)
        if label is not None and label.get_string() == "_Help":
            help_menu = menu.get_item_link(i, "submenu")
            return [
                help_menu.get_item_attribute_value(
                    j, "action", None
                ).get_string()
                for j in range(help_menu.get_n_items())
            ]
    return []


def _rows(window: ToursWindow) -> list[Adw.ActionRow]:
    rows = []
    row = window.list.get_first_child()
    while row is not None:
        rows.append(row)
        row = row.get_next_sibling()
    return rows


@pytest.mark.ui
def test_help_lists_the_tours_and_start_plays_one(main_window):
    win = main_window
    config = get_context().config
    config.mark_tour(FIRST_CUT.id, TOUR_COMPLETED)
    config.mark_tour(POSITIONING.id, TOUR_SEEN)
    assert "win.tours" in _help_actions(win)

    win.activate_action("win.tours", None)
    _pump(0.2)

    (window,) = _windows(ToursWindow)
    assert window.get_transient_for() is win
    assert [
        (row.get_title(), row.get_subtitle()) for row in _rows(window)
    ] == [
        ("Your First Cut", "Completed"),
        ("Layers Explained", "Not taken yet"),
        ("Positioning", "Skipped part way"),
    ]

    window.start_buttons[LAYERS.id].emit("clicked")
    _pump(0.3)

    assert _windows(ToursWindow) == []
    assert win.tour is not None and win.tour.tour is LAYERS
    assert win.tour.bubble.get_visible()


@pytest.mark.ui
def test_start_tour_ignores_an_unknown_tour(main_window):
    win = main_window

    win.activate_action("win.start-tour", GLib.Variant.new_string("nope"))
    _pump(0.1)

    assert win.tour is None


# --- After the first-run guide ------------------------------------------


def _close_the_guide(win):
    from swiftcut.ui_gtk.getting_started import GettingStartedWindow

    (guide,) = _windows(GettingStartedWindow)
    guide.close()
    _pump(0.3)


@pytest.mark.ui
def test_your_first_cut_plays_once_after_the_first_guide(main_window):
    win = main_window
    config = get_context().config

    win.maybe_show_getting_started(scripted=False)
    _pump(0.2)
    # Not over the guide: once it is closed.
    assert win.tour is None
    _close_the_guide(win)

    assert win.tour is not None and win.tour.tour is FIRST_CUT
    win.tour.skip()
    assert config.tours[FIRST_CUT.id] == TOUR_SEEN

    # Were the guide to open by itself again, the tour would not.
    config.set_getting_started_seen(False)
    win.maybe_show_getting_started(scripted=False)
    _pump(0.2)
    _close_the_guide(win)
    assert win.tour is None


@pytest.mark.ui
def test_a_completed_first_cut_never_plays_after_the_guide(main_window):
    win = main_window
    get_context().config.mark_tour(FIRST_CUT.id, TOUR_COMPLETED)

    win.maybe_show_getting_started(scripted=False)
    _pump(0.2)
    _close_the_guide(win)

    assert win.tour is None


@pytest.mark.ui
def test_no_tour_in_a_scripted_run_or_after_the_guide_from_help(
    main_window,
):
    from swiftcut.ui_gtk.getting_started import GettingStartedWindow

    win = main_window
    context = get_context()

    # --uiscript and --exit, and a run that exits once settled: no
    # guide opens, so no tour follows it.
    win.maybe_show_getting_started(scripted=True)
    context.exit_after_settle = True
    try:
        win.maybe_show_getting_started(scripted=False)
    finally:
        context.exit_after_settle = False
    _pump(0.3)
    assert _windows(GettingStartedWindow) == []
    assert win.tour is None

    # The guide opened from Help is not the first run's.
    win.activate_action("win.getting-started", None)
    _pump(0.2)
    _close_the_guide(win)
    assert win.tour is None
    assert context.config.tours == {}
