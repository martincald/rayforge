"""
The job preview's transport, beside the time estimate on the canvas.

A Preview toggle; once the preview is loaded, play/pause, a scrub
bar, the elapsed and total time and the playback speed. The bar keeps
the preview's clock and says when it moves; the window draws it and
drives it from the canvas' frame clock.
"""

from gettext import gettext as _

from blinker import Signal
from gi.repository import Gtk

from ...shared.util.time_format import format_clock
from ..icons import get_icon
from ..layout import OVERLAY_PANEL_WIDTH, SPACE_TIGHT

#: The playback speeds, as multiples of the estimated speed.
SPEEDS = (1, 4, 16)


class JobPreviewBar(Gtk.Box):
    """
    Signals:
        preview_toggled(active): the Preview toggle changed.
        time_changed(time): the preview's time moved, in seconds.
        playing_changed(playing): playback started or stopped.
    """

    def __init__(self, **kwargs):
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=SPACE_TIGHT,
            **kwargs,
        )
        self.preview_toggled = Signal()
        self.time_changed = Signal()
        self.playing_changed = Signal()

        self.total = 0.0
        self.time = 0.0
        self.playing = False
        self.speed = SPEEDS[0]
        # Set while the scrub bar is moved to follow the time.
        self._following = False

        self.toggle = Gtk.ToggleButton(label=_("Preview"))
        self.toggle.set_tooltip_text(
            _("Preview the job in the order it runs, at its estimated speed")
        )
        self.toggle.connect("toggled", self._on_toggled)
        self.append(self.toggle)

        # The transport, shown once a preview is loaded.
        self.controls = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=SPACE_TIGHT
        )
        self.controls.set_visible(False)
        self.append(self.controls)

        self._play_icon = get_icon("play-arrow-symbolic")
        self._pause_icon = get_icon("pause-symbolic")
        self.play_button = Gtk.Button()
        self.play_button.add_css_class("sc-icon-button")
        self.play_button.connect("clicked", self._on_play_clicked)
        self.controls.append(self.play_button)

        self.scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.1
        )
        self.scale.set_draw_value(False)
        # Half a floating panel: room to scrub without covering the work.
        self.scale.set_size_request(OVERLAY_PANEL_WIDTH // 2, -1)
        self.scale.connect("value-changed", self._on_scale_changed)
        self.controls.append(self.scale)

        self.label = Gtk.Label()
        self.label.add_css_class("sc-numeric")
        self.controls.append(self.label)

        speeds = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        speeds.add_css_class("linked")
        self.speed_buttons: dict[int, Gtk.ToggleButton] = {}
        for speed in SPEEDS:
            button = Gtk.ToggleButton(label=f"x{speed}")
            button.set_tooltip_text(
                _("Play at {speed} times the estimated speed").format(
                    speed=speed
                )
            )
            if self.speed_buttons:
                button.set_group(self.speed_buttons[SPEEDS[0]])
            button.set_active(speed == self.speed)
            button.connect("toggled", self._on_speed_toggled, speed)
            speeds.append(button)
            self.speed_buttons[speed] = button
        self.controls.append(speeds)

        self._show_playing()

    @property
    def active(self) -> bool:
        return self.toggle.get_active()

    def load(self, total: float):
        """A preview total seconds long is ready: play it from 0."""
        self.total = max(total, 0.0)
        self._following = True
        self.scale.set_range(0.0, max(self.total, 0.1))
        self._following = False
        self.controls.set_visible(True)
        self.set_time(0.0)
        self.set_playing(True)

    def reset(self):
        """Leave the preview: the toggle off and the transport gone."""
        self.toggle.set_active(False)

    def set_time(self, time: float):
        """Move the preview to a time, clamped to its length."""
        self.time = min(max(time, 0.0), self.total)
        self._following = True
        self.scale.set_value(self.time)
        self._following = False
        self.label.set_text(
            f"{format_clock(self.time)} / {format_clock(self.total)}"
        )
        self.time_changed.send(self, time=self.time)

    def set_playing(self, playing: bool):
        if playing == self.playing:
            return
        self.playing = playing
        self._show_playing()
        self.playing_changed.send(self, playing=playing)

    def advance(self, seconds: float):
        """
        One frame of playback: seconds of real time, run at the
        chosen speed. Pauses at the end.
        """
        if not self.playing:
            return
        self.set_time(self.time + seconds * self.speed)
        if self.time >= self.total:
            self.set_playing(False)

    def _show_playing(self):
        if self.playing:
            self.play_button.set_child(self._pause_icon)
            self.play_button.set_tooltip_text(_("Pause"))
        else:
            self.play_button.set_child(self._play_icon)
            self.play_button.set_tooltip_text(_("Play"))

    def _on_toggled(self, toggle):
        if not toggle.get_active():
            self.set_playing(False)
            self.controls.set_visible(False)
            self.total = 0.0
            self.time = 0.0
        self.preview_toggled.send(self, active=toggle.get_active())

    def _on_play_clicked(self, button):
        if not self.playing and self.time >= self.total:
            # Played to the end: Play starts it over.
            self.set_time(0.0)
        self.set_playing(not self.playing)

    def _on_scale_changed(self, scale):
        if not self._following:
            self.set_time(scale.get_value())

    def _on_speed_toggled(self, button, speed: int):
        if button.get_active():
            self.speed = speed
