"""The guided tour's engine: the dim and its hole, the shield around the
hole, the bubble, and the steps that move on when the user does what
they ask.

The tours themselves are not here; a small tour of this file's own
drives the engine. No step sends the machine anything: a connected
machine is faked, and every command the jog panel could send is
stubbed.
"""

import math
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, patch

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk  # noqa: E402

from swiftcut.context import get_context  # noqa: E402
from swiftcut.core.config import TOUR_COMPLETED, TOUR_SEEN  # noqa: E402
from swiftcut.core.layer import Layer  # noqa: E402
from swiftcut.core.workpiece import WorkPiece  # noqa: E402
from swiftcut.machine.transport.transport import (  # noqa: E402
    TransportStatus,
)
from swiftcut.ui_gtk.layout import SPACE_GROUP  # noqa: E402
from swiftcut.ui_gtk.machine.start_position_dialog import (  # noqa: E402
    start_chosen,
)
from swiftcut.ui_gtk.tour import targets  # noqa: E402
from swiftcut.ui_gtk.tour.overlay import (  # noqa: E402
    HOLE_PAD,
    hole_rect,
    target_hole,
)
from swiftcut.ui_gtk.tour.runner import Step, Tour, TourRunner  # noqa: E402


def _has_workpiece(win, **details):
    return win.doc_editor.doc.has_workpiece()


def _connected(win, status=None, **details):
    return status == TransportStatus.CONNECTED


DEMO = Tour(
    id="demo",
    title="Demo",
    steps=(
        Step(
            "Import",
            "Bring in a drawing.",
            target="toolbar.import",
            advance_on=("doc-added",),
            done=_has_workpiece,
        ),
        Step(
            "Connect",
            "Plug in the laser.",
            target="jog.pad",
            advance_on=("connection",),
            done=_connected,
            connection_status=True,
        ),
        Step(
            "Go Scale",
            "Trace the outline.",
            target="jog.go-scale",
            unavailable="Connect the laser first.",
        ),
        Step(
            "Start",
            "Run the job.",
            target="jog.start",
            advance_on=("start",),
        ),
        Step("Done", "That is all."),
    ),
)


def _pump(seconds: float) -> None:
    end = time.monotonic() + seconds
    context = GLib.main_context_default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


@pytest.fixture
def main_window(ui_context_initializer):
    from swiftcut.ui_gtk.mainwindow import MainWindow

    class App(Adw.Application):
        def do_activate(self):
            self.win = MainWindow(application=self)
            self.win.set_default_size(1280, 800)

    app = App(application_id="org.swiftcut.swiftcut.test.tour")
    app.register(None)
    app.activate()
    win = app.win
    win.present()
    _pump(0.3)
    yield win
    win.doc_editor.cleanup()
    # A tour still playing goes with its window.
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


def _start(win, tour: Tour = DEMO, at: int = 0) -> TourRunner:
    runner = TourRunner(win, tour)
    runner.start()
    for _ in range(at):
        runner.next()
    _pump(0.3)
    return runner


def _center(widget, reference) -> tuple[float, float]:
    ok, bounds = widget.compute_bounds(reference)
    assert ok
    return (
        bounds.get_x() + bounds.get_width() / 2,
        bounds.get_y() + bounds.get_height() / 2,
    )


def _pick(win, widget):
    """What a click at the middle of widget lands on."""
    x, y = _center(widget, win.tour_overlay)
    return win.tour_overlay.pick(x, y, Gtk.PickFlags.DEFAULT)


def _is_within(widget, ancestor) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.get_parent()
    return False


def _rect(bounds) -> tuple[float, float, float, float]:
    return (
        bounds.get_x(),
        bounds.get_y(),
        bounds.get_width(),
        bounds.get_height(),
    )


def _overlay_children(overlay):
    child = overlay.get_first_child()
    while child is not None:
        if child is not overlay.get_child():
            yield child
        child = child.get_next_sibling()


def _controllers(widget) -> list:
    model = widget.observe_controllers()
    return [model.get_item(i) for i in range(model.get_n_items())]


# --- The hole ---------------------------------------------------------


def test_the_hole_rounds_out_to_whole_device_pixels():
    bounds = (10.25, 20.5, 30.0, 40.0)

    # At 1x a device pixel is a logical one; at 2x it is half of one.
    assert hole_rect(bounds, [], scale=1, pad=0) == (10.0, 20.0, 31.0, 41.0)
    assert hole_rect(bounds, [], scale=2, pad=0) == (10.0, 20.5, 30.5, 40.0)

    # Bounds on the pixel grid are the hole, grown by the pad.
    for scale in (1, 2):
        assert hole_rect((10.0, 20.0, 30.0, 40.0), [], scale, pad=4) == (
            6.0,
            16.0,
            38.0,
            48.0,
        )


def test_the_hole_is_cut_to_the_scrollers_its_target_shows_through():
    scroller = (0.0, 0.0, 50.0, 100.0)

    # Half scrolled out at the scroller's right edge.
    assert hole_rect((40, 10, 20, 10), [scroller], 2, pad=4) == (
        36.0,
        6.0,
        14.0,
        18.0,
    )
    # Scrolled away altogether: no hole.
    assert hole_rect((60, 10, 20, 10), [scroller], 2, pad=4) is None


@pytest.mark.ui
def test_the_hole_is_the_targets_bounds_at_the_live_scale(main_window):
    win = main_window
    runner = _start(win)
    button = targets.find(win, "toolbar.import")
    overlay = win.tour_overlay
    scale = win.get_surface().get_scale()
    ok, bounds = button.compute_bounds(overlay)
    assert ok
    x, y, width, height = _rect(bounds)

    window = (0.0, 0.0, overlay.get_width(), overlay.get_height())
    assert runner.mask.hole == hole_rect(_rect(bounds), [window], scale)
    assert runner.shield.hole == runner.mask.hole
    # The toolbar sits on the device pixel grid, so nothing rounds:
    # the hole is the button's bounds and the pad, exactly.
    assert runner.mask.hole == (
        x - HOLE_PAD,
        y - HOLE_PAD,
        width + 2 * HOLE_PAD,
        height + 2 * HOLE_PAD,
    )
    print(f"live scale {scale}, hole {runner.mask.hole}")


def _render(widget):
    """widget as drawn now, as straight RGBA bytes, one per channel."""
    width, height = widget.get_width(), widget.get_height()
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, width, height)
    texture = (
        widget.get_native()
        .get_renderer()
        .render_texture(snapshot.to_node(), None)
    )
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
    data, stride = downloader.download_bytes()
    pixels = data.get_data()
    scale = texture.get_width() / width

    def alpha(x: float, y: float) -> int:
        return pixels[int(y * scale) * stride + int(x * scale) * 4 + 3]

    return alpha


@pytest.mark.ui
def test_the_mask_dims_all_but_the_hole(main_window):
    win = main_window
    runner = _start(win)
    hole_x, hole_y, hole_width, hole_height = runner.mask.hole
    alpha = _render(runner.mask)

    assert alpha(hole_x + hole_width / 2, hole_y + hole_height / 2) == 0
    dim = round(255 * runner.mask.scrim().alpha)
    assert abs(alpha(*_center(win.surface, runner.mask)) - dim) <= 1
    assert abs(alpha(hole_x + hole_width + 2, hole_y) - dim) <= 1


@pytest.mark.ui
def test_the_dim_is_deeper_in_the_dark_theme(ui_context_initializer):
    from swiftcut.ui_gtk.tour.overlay import (
        SCRIM_ALPHA_DARK,
        SCRIM_ALPHA_LIGHT,
        TourMask,
    )

    style = Adw.StyleManager.get_default()
    scheme = style.get_color_scheme()
    try:
        style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        light = TourMask.scrim()
        style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        dark = TourMask.scrim()
    finally:
        style.set_color_scheme(scheme)

    assert (light.red, light.green, light.blue) == (0, 0, 0)
    assert light.alpha == pytest.approx(SCRIM_ALPHA_LIGHT)
    assert dark.alpha == pytest.approx(SCRIM_ALPHA_DARK)
    assert dark.alpha > light.alpha


@pytest.mark.ui
def test_every_target_is_found_in_a_fresh_window(main_window):
    win = main_window

    for target_id in targets.TARGETS:
        targets.prepare(win, target_id)
        assert targets.find(win, target_id) is not None, target_id


@pytest.mark.ui
def test_the_hole_follows_a_card_rebuilt_under_it(main_window):
    win = main_window
    tour = Tour(
        "card", "Card", (Step("Card", "A layer.", "layers.active-card"),)
    )
    runner = _start(win, tour)
    first = targets.find(win, "layers.active-card")
    assert runner.mask.hole == target_hole(first, win.tour_overlay)

    # A change to the layers rebuilds every card.
    win.doc_editor.doc.add_layer(Layer("Second"))
    _pump(0.3)

    card = targets.find(win, "layers.active-card")
    assert card is not first
    assert runner.mask.hole == target_hole(card, win.tour_overlay)


@pytest.mark.ui
def test_the_bubble_points_at_its_hole(main_window):
    win = main_window
    runner = _start(win)
    bubble = runner.bubble
    popup = bubble.get_surface()
    assert bubble.get_visible() and bubble.get_has_arrow()
    assert isinstance(popup, Gdk.Popup)

    # The toolbar is in the window's upper half: the bubble hangs
    # below it, its arrow on the hole's bottom edge. The popup's own
    # surface reaches a shadow's width past the arrow.
    assert bubble.get_position() == Gtk.PositionType.BOTTOM
    assert _pointing_to(bubble) == _whole(runner.mask.hole)
    tip = _surface_y(win, runner.mask.hole[1] + runner.mask.hole[3])
    top = popup.get_position_y()
    assert tip - _SHADOW <= top <= tip

    # The dock is in the lower half: the bubble stands above it.
    runner.next()
    _pump(0.3)
    assert bubble.get_position() == Gtk.PositionType.TOP
    assert _pointing_to(bubble) == _whole(runner.mask.hole)
    tip = _surface_y(win, runner.mask.hole[1])
    bottom = popup.get_position_y() + popup.get_height()
    assert tip <= bottom <= tip + _SHADOW


# The most a popover's surface reaches past its arrow's tip.
_SHADOW = 32


@pytest.mark.ui
def test_the_bubble_stays_in_the_window_and_centres_in_a_tall_hole(
    main_window, connected
):
    win = main_window
    tour = Tour(
        "edge",
        "Edge",
        (
            Step("Start", "By the window's edge.", "jog.start"),
            Step("Canvas", "Too tall to stand beside.", "canvas"),
        ),
    )
    runner = _start(win, tour)
    bubble = runner.bubble
    width = win.tour_overlay.get_width()

    # Centred on Start it would cross the window's right edge: it
    # slides in, and its arrow still points at the hole.
    assert bubble.get_has_arrow()
    assert bubble.get_offset()[0] < 0
    assert _pointing_to(bubble) == _whole(runner.mask.hole)
    x, y, content_width, content_height = _in_overlay(win, bubble)
    assert x + content_width <= width - SPACE_GROUP
    assert x >= 0

    # The canvas's hole is too tall to stand beside: the bubble sits in
    # its middle, with no arrow to point at nothing.
    runner.next()
    _pump(0.3)
    hole_x, hole_y, hole_width, hole_height = runner.mask.hole
    assert hole_height > win.tour_overlay.get_height() * 0.4
    assert not bubble.get_has_arrow()
    x, y, content_width, content_height = _in_overlay(win, bubble)
    assert abs(x + content_width / 2 - (hole_x + hole_width / 2)) <= 1
    assert (
        abs(y + content_height / 2 - (hole_y + hole_height / 2)) <= SPACE_GROUP
    )


@pytest.mark.ui
def test_the_bubble_keeps_off_stop_and_pause(main_window, connected):
    win = main_window
    jog = win.bottom_panel.jog_widget
    tour = Tour(
        "clear",
        "Clear",
        (Step("Cut Scale", "Beside Stop and Pause.", "jog.cut-scale"),),
    )
    runner = _start(win, tour)
    bubble = runner.bubble

    # Centred on Cut Scale it would lie over Stop and Pause, to its
    # right: it slides left off them, shadow and all, and its arrow
    # still points at the hole. A click on them reaches them.
    assert bubble.get_has_arrow()
    assert _pointing_to(bubble) == _whole(runner.mask.hole)
    _assert_clear(win, bubble, (jog.stop_btn, jog.pause_btn))

    # With such controls close on both sides of the hole, no slide
    # clears them all: the bubble goes to the window's middle, with no
    # arrow. The left one reaches from there, and the bubble slides
    # off it, still off Stop and Pause. The runner's layout has not
    # changed, so the next frame leaves the bubble where it is.
    x, _, width, _ = runner.mask.hole
    overlay = win.tour_overlay
    middle_x, middle_y = overlay.get_width() / 2, overlay.get_height() / 2
    below = overlay.get_height() - middle_y
    walls = [
        (middle_x, middle_y, x - 10 - middle_x, below),
        (x + width + 10, middle_y, 400, below),
    ]
    bubble.point_at(
        runner.mask.hole,
        overlay.get_width(),
        overlay.get_height(),
        [*walls, *runner._keep_clear()],
    )
    runner.mask.queue_allocate()
    _pump(0.3)
    popup = _popup_in_overlay(win, bubble)
    for wall in walls:
        assert not _overlap(popup, wall), wall
    _assert_clear(win, bubble, (jog.stop_btn, jog.pause_btn))
    assert not bubble.get_has_arrow()
    assert bubble.get_offset()[0] < 0


@pytest.mark.ui
def test_a_bubble_with_no_room_beside_its_hole_keeps_off_stop_and_pause(
    main_window, connected, monkeypatch
):
    from swiftcut.ui_gtk.tour import overlay

    win = main_window
    jog = win.bottom_panel.jog_widget
    # No bubble has room enough for its arrow: every one beside a hole
    # goes to the middle instead.
    monkeypatch.setattr(overlay, "_ARROW_ROOM", 1000)
    tour = Tour(
        "fallback",
        "Fallback",
        (Step("Cut Scale", "Beside Stop and Pause.", "jog.cut-scale"),),
    )
    runner = _start(win, tour)
    bubble = runner.bubble

    # The window's middle, not the hole's: in the hole's, by Cut Scale,
    # it would lie over Stop and Pause.
    assert runner.mask.hole is not None
    _assert_clear(win, bubble, (jog.stop_btn, jog.pause_btn))
    assert not bubble.get_has_arrow()
    x, _, content_width, _ = _in_overlay(win, bubble)
    assert abs(x + content_width / 2 - win.tour_overlay.get_width() / 2) <= 1


def _assert_clear(win, bubble, buttons):
    """The popup lies off each button, and a click on one reaches it."""
    popup = _popup_in_overlay(win, bubble)
    for button in buttons:
        ok, bounds = button.compute_bounds(win.tour_overlay)
        assert ok
        assert not _overlap(popup, _rect(bounds)), button
        assert _bubble_pick(win, bubble, button) is None, button
        assert _is_within(_pick(win, button), button), button


def _overlap(a, b) -> bool:
    return (
        a[0] < b[0] + b[2]
        and b[0] < a[0] + a[2]
        and a[1] < b[1] + b[3]
        and b[1] < a[1] + a[3]
    )


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


def _bubble_pick(win, bubble, widget):
    """What, in the bubble, a click at the middle of widget lands on."""
    x, y = _center(widget, win.tour_overlay)
    popup_x, popup_y = _popup_origin(win, bubble)
    bubble_x, bubble_y = bubble.get_surface_transform()
    return bubble.pick(
        x - popup_x - bubble_x, y - popup_y - bubble_y, Gtk.PickFlags.DEFAULT
    )


def _in_overlay(win, bubble) -> tuple[float, float, float, float]:
    """The bubble's content, in the tour overlay's coordinates."""
    ok, bounds = bubble.get_child().compute_bounds(bubble)
    assert ok
    popup_x, popup_y = _popup_origin(win, bubble)
    bubble_x, bubble_y = bubble.get_surface_transform()
    return (
        popup_x + bubble_x + bounds.get_x(),
        popup_y + bubble_y + bounds.get_y(),
        bounds.get_width(),
        bounds.get_height(),
    )


def _pointing_to(bubble) -> tuple[int, int, int, int]:
    ok, rect = bubble.get_pointing_to()
    assert ok
    return rect.x, rect.y, rect.width, rect.height


def _whole(hole) -> tuple[int, int, int, int]:
    x, y, width, height = hole
    return (
        math.floor(x),
        math.floor(y),
        math.ceil(x + width) - math.floor(x),
        math.ceil(y + height) - math.floor(y),
    )


def _surface_y(win, y: float) -> float:
    """A y in the tour overlay, in the window surface's coordinates."""
    ok, point = win.tour_overlay.compute_point(
        win, Graphene.Point().init(0, y)
    )
    assert ok
    return point.y + win.get_surface_transform()[1]


# --- The shield -------------------------------------------------------


@pytest.mark.ui
def test_the_shield_takes_clicks_outside_the_hole_only(main_window):
    win = main_window
    runner = _start(win)
    button = targets.find(win, "toolbar.import")

    assert _is_within(_pick(win, button), button)
    assert _pick(win, win.surface) is runner.shield
    assert _pick(win, win.toolbar.open_button) is runner.shield
    assert _pick(win, win.bottom_panel.layers_tab) is runner.shield


@pytest.mark.ui
def test_stop_pause_and_a_running_go_scale_are_never_covered(
    main_window, connected
):
    win = main_window
    runner = _start(win)
    jog = win.bottom_panel.jog_widget
    assert jog.machine_cmd is win.machine_cmd

    for widget in (jog.stop_btn, jog.pause_btn, win.toolbar.cancel_button):
        assert widget.get_mapped() and widget.is_sensitive(), widget
        assert _is_within(_pick(win, widget), widget), widget
    # The toolbar's Pause is on only while a job runs; it passes too.
    assert win.toolbar.hold_button in runner.shield.passes()

    # Go Scale is covered like any control, until it turns into the
    # Stop of the scale it started.
    assert jog.go_scale_btn.is_sensitive()
    assert _pick(win, jog.go_scale_btn) is runner.shield
    jog.go_scale_btn.emit("clicked")
    _pump(0.1)
    win.machine_cmd.run_go_scale.assert_called_once()
    assert jog.go_scale_btn.has_css_class("destructive-action")
    assert _is_within(_pick(win, jog.go_scale_btn), jog.go_scale_btn)

    controls = [
        widget
        for widget in runner.shield.passes()
        if isinstance(widget, Gtk.WindowControls) and widget.get_mapped()
    ]
    for widget in controls:
        assert not runner.shield.contains(*_center(widget, runner.shield))
    print(f"window controls passed through: {len(controls)}")


@pytest.mark.ui
def test_a_jog_press_in_the_hole_keeps_its_release(main_window, connected):
    """
    A press on a jog arrow in the hole belongs to the arrow's hold
    gesture, and GTK sends that press's release to the arrow wherever
    the pointer is by then (an implicit grab). The shield must neither
    take the press, nor hold anything that could take the release, nor
    cancel the gesture by hiding or switching off what it holds.

    Headless GTK cannot press a real pointer, so the grab itself is not
    exercised here: that needs a real mouse.
    """
    win = main_window
    jog = win.bottom_panel.jog_widget
    arrow = jog.north_btn
    chain = []
    widget = arrow
    while widget is not None:
        chain.append(widget)
        widget = widget.get_parent()
    before = {id(widget): _controllers(widget) for widget in chain}
    # The hold gesture, and any other the arrow's click runs through.
    gestures = [
        controller
        for controller in _controllers(arrow)
        if isinstance(controller, Gtk.Gesture)
    ]
    assert gestures
    cancels = []
    for gesture in gestures:
        gesture.connect("cancel", lambda *args: cancels.append(args))

    runner = _start(win, at=1)
    assert runner.step.target == "jog.pad"
    # A bubble that hid by itself would grab the pointer as it opened.
    assert not runner.bubble.get_autohide()

    # The press lands on the arrow; a release over the canvas would
    # land on the shield, which has no controller at all.
    assert _is_within(_pick(win, arrow), arrow)
    assert _pick(win, win.surface) is runner.shield
    assert _controllers(runner.shield) == []
    # Above the arrow the tour adds only its Esc key controller.
    for widget in chain:
        added = [
            c for c in _controllers(widget) if c not in before[id(widget)]
        ]
        assert added == ([runner.keys] if widget is win else []), widget

    # Moving the hole, hiding the tour and ending it leave the arrow
    # shown and on, and its gesture uncancelled.
    for change in (
        runner.next,
        runner.back,
        lambda: _show_page(win, "elsewhere"),
        lambda: _show_page(win, "main"),
        runner.skip,
    ):
        change()
        _pump(0.1)
        assert arrow.get_mapped() and arrow.is_sensitive()
    assert cancels == []


def _show_page(win, name: str):
    if win.main_stack.get_child_by_name(name) is None:
        win.main_stack.add_named(Gtk.Box(), name)
    win.main_stack.set_visible_child_name(name)


# --- Steps that move on -----------------------------------------------


@pytest.mark.ui
def test_a_step_moves_on_when_the_document_gains_a_workpiece(main_window):
    win = main_window
    runner = _start(win)
    assert runner.index == 0

    # Another layer is not what the step asks for.
    win.doc_editor.layer.add_layer_and_set_active()
    _pump(0.2)
    assert runner.index == 0

    win.doc_editor.doc.active_layer.add_child(WorkPiece(name="square"))
    _pump(0.2)
    assert runner.index == 1


@pytest.mark.ui
def test_the_connect_step_moves_on_once_connected(main_window):
    win = main_window
    with _fake_driver(win) as machine:
        runner = _start(win, at=1)
        status = runner.bubble.connection_status
        assert status.get_visible() and status.machine is machine

        _set_status(machine, TransportStatus.CONNECTING)
        _pump(0.2)
        assert runner.index == 1

        _set_status(machine, TransportStatus.CONNECTED)
        _pump(0.2)
        assert runner.index == 2
        assert not status.get_visible() and status.machine is None


@pytest.mark.ui
def test_the_start_step_moves_on_for_a_start_in_this_window(main_window):
    win = main_window
    machine = get_context().config.machine
    runner = _start(win, at=3)

    start_chosen.send(object(), machine=machine)
    _pump(0.2)
    assert runner.index == 3

    start_chosen.send(win, machine=machine)
    _pump(0.2)
    assert runner.index == 4


@pytest.mark.ui
def test_a_control_that_is_off_gets_a_bubble_in_the_middle(main_window):
    win = main_window
    runner = _start(win, at=2)
    go_scale = win.bottom_panel.jog_widget.go_scale_btn
    assert go_scale.get_mapped() and not go_scale.is_sensitive()

    assert runner.mask.hole is None and runner.shield.hole is None
    assert not runner.bubble.get_has_arrow()
    assert runner.bubble.reason.get_visible()
    assert runner.bubble.reason.get_label() == "Connect the laser first."
    assert runner.bubble.next_button.is_sensitive()
    assert _pick(win, go_scale) is runner.shield


# --- Next, Back, Skip, Esc --------------------------------------------


@pytest.mark.ui
def test_next_and_back_walk_the_steps_and_skip_ends_it(main_window):
    win = main_window
    config = get_context().config
    runner = _start(win)
    bubble = runner.bubble
    assert bubble.counter.get_label() == "1 of 5"
    assert not bubble.back_button.get_sensitive()

    # The bubble is a window of its own, over the shield: a click on
    # its buttons lands on them.
    for button in (bubble.next_button, bubble.skip_button):
        x, y = _center(button, bubble)
        assert _is_within(bubble.pick(x, y, Gtk.PickFlags.DEFAULT), button)

    bubble.next_button.emit("clicked")
    assert runner.index == 1 and bubble.counter.get_label() == "2 of 5"
    bubble.back_button.emit("clicked")
    assert runner.index == 0
    assert "demo" not in config.tours

    bubble.skip_button.emit("clicked")
    _pump(0.1)

    assert win.tour is None
    assert config.tours["demo"] == TOUR_SEEN
    assert list(_overlay_children(win.tour_overlay)) == []
    assert runner.keys not in _controllers(win)
    assert not bubble.get_visible()


@pytest.mark.ui
def test_done_on_the_last_step_records_the_tour_completed(main_window):
    win = main_window
    runner = _start(win, at=4)
    bubble = runner.bubble
    assert bubble.next_button.get_label() == "Done"
    assert not bubble.skip_button.get_visible()

    bubble.next_button.emit("clicked")
    _pump(0.1)

    assert win.tour is None
    assert get_context().config.tours["demo"] == TOUR_COMPLETED


@pytest.mark.ui
def test_a_new_tour_ends_the_one_playing_unrecorded(main_window):
    win = main_window
    first = _start(win)
    second = _start(win, Tour("other", "Other", (Step("One", "Only."),)))

    assert win.tour is second and not first.active
    assert get_context().config.tours == {}
    assert len(list(_overlay_children(win.tour_overlay))) == 2


@pytest.mark.ui
def test_esc_ends_the_tour_before_the_window_sees_it(main_window):
    win = main_window
    runner = _start(win)
    keys = runner.keys
    assert keys.get_widget() is win
    assert keys.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE
    no_mods = Gdk.ModifierType(0)

    # Every other key goes on to the window: shortcuts, jog keys.
    assert keys.emit("key-pressed", Gdk.KEY_Left, 0, no_mods) is False
    assert keys.emit("key-pressed", Gdk.KEY_Escape, 0, no_mods) is True
    _pump(0.1)

    assert win.tour is None
    assert get_context().config.tours["demo"] == TOUR_SEEN


@pytest.mark.ui
def test_another_page_hides_the_tour_and_keeps_its_own_esc(main_window):
    win = main_window
    runner = _start(win)

    _show_page(win, "elsewhere")
    _pump(0.2)
    assert not runner.mask.get_visible()
    assert not runner.shield.get_visible()
    assert not runner.bubble.get_visible()
    no_mods = Gdk.ModifierType(0)
    assert runner.keys.emit("key-pressed", Gdk.KEY_Escape, 0, no_mods) is False

    _show_page(win, "main")
    _pump(0.3)
    assert runner.mask.get_visible() and runner.shield.get_visible()
    assert runner.bubble.get_visible()
    assert win.tour is runner
