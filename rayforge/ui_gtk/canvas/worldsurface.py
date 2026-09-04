import logging
import math
import time

from gi.repository import Gdk, GLib, Graphene, Gtk
from raygeo.geo import Matrix

from ..shared.keyboard import is_primary_modifier
from .axis import AxisRenderer
from .camera import Camera
from .camera_animator import CameraAnimator
from .canvas import Canvas

logger = logging.getLogger(__name__)

# Geometric factor applied per discrete zoom step (mouse wheel notch,
# keyboard +/-, Ctrl+1).
DISCRETE_ZOOM_FACTOR = 1.1

# Sensitivity of continuous (trackpad Ctrl+smooth-scroll) zooming: the
# zoom multiplier for a scroll delta of dy is exp(-dy * sensitivity).
TRACKPAD_ZOOM_SENSITIVITY = 0.1

# Trackpad-flick inertia: velocity decays by this factor every frame,
# and stops once both axes are below the threshold (in px/frame).
INERTIA_DECAY = 0.92
INERTIA_STOP_THRESHOLD_PX_PER_FRAME = 0.5


def _decay_pan_velocity(
    vx_px_per_frame: float, vy_px_per_frame: float
) -> tuple[float, float] | None:
    """
    Applies one frame of trackpad-flick inertia decay to a pan
    velocity. Returns the new (vx, vy) in px/frame, or None once both
    components have decayed below the stop threshold (the caller
    should stop ticking).
    """
    vx = vx_px_per_frame * INERTIA_DECAY
    vy = vy_px_per_frame * INERTIA_DECAY
    if (
        abs(vx) < INERTIA_STOP_THRESHOLD_PX_PER_FRAME
        and abs(vy) < INERTIA_STOP_THRESHOLD_PX_PER_FRAME
    ):
        return None
    return vx, vy


class WorldSurface(Canvas):
    """
    The WorldSurface provides a generic canvas with a real-world coordinate
    system (in millimeters), a grid, axes, and interactive pan/zoom controls.
    It is the base class for more specific surfaces like the WorkSurface.
    """

    # The minimum allowed zoom level, relative to the "fit-to-view" size
    # (zoom=1.0). 0.1 means you can zoom out until the view is 10% of its
    # "fit" size.
    MIN_ZOOM_FACTOR = 0.1

    # The maximum allowed pixel density when zooming in.
    MAX_PIXELS_PER_MM = 100.0

    # Soft pan clamp: panning may not move the bed so far that less
    # than this fraction of its width/height remains visible in the
    # viewport. Applied to the pan offset, not to zoom (see
    # _update_pan_bounds / _ease_pan_into_bounds). It is "soft": an
    # active gesture (drag/inertia) may transiently overshoot it, and
    # is eased back into bounds once the gesture ends.
    MIN_VISIBLE_BED_FRACTION = 0.2

    def __init__(
        self,
        width_mm: float = 100.0,
        height_mm: float = 100.0,
        x_axis_right: bool = False,
        y_axis_down: bool = False,
        reverse_x_axis: bool = False,
        reverse_y_axis: bool = False,
        show_grid: bool = True,
        show_axis: bool = True,
        **kwargs,
    ):
        logger.debug("WorldSurface.__init__ called")
        super().__init__(**kwargs)
        self.grid_size = 1.0  # Set snap grid to 1mm in world coordinates
        self._camera = Camera()
        self._last_view_scale_x: float = 0.0
        self._last_view_scale_y: float = 0.0
        self.width_mm = width_mm
        self.height_mm = height_mm

        # The root element is now static and sized in world units (mm).
        self.root.set_size(self.width_mm, self.height_mm)
        self.root.clip = False

        self._axis_renderer = AxisRenderer(
            width_mm=self.width_mm,
            height_mm=self.height_mm,
            x_axis_right=x_axis_right,
            y_axis_down=y_axis_down,
            x_axis_negative=reverse_x_axis,
            y_axis_negative=reverse_y_axis,
            show_grid=show_grid,
            show_axis=show_axis,
        )
        self.root.background = 0.8, 0.8, 0.8, 0.1

        # Set theme colors for axis and grid.
        self._update_theme_colors()

        # Add scroll event controller for zoom (wheel, Ctrl+trackpad) and
        # two-finger trackpad panning. BOTH_AXES (rather than the old
        # VERTICAL-only) lets GTK report smooth, per-axis deltas for
        # trackpads alongside discrete wheel notches; KINETIC enables the
        # "decelerate" signal used for trackpad-flick pan inertia.
        self._scroll_controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES
            | Gtk.EventControllerScrollFlags.KINETIC
        )
        self._scroll_controller.connect("scroll", self.on_scroll)
        self._scroll_controller.connect(
            "decelerate", self.on_scroll_decelerate
        )
        self.add_controller(self._scroll_controller)

        # Add middle click gesture for panning
        self._pan_gesture = Gtk.GestureDrag.new()
        self._pan_gesture.set_button(Gdk.BUTTON_MIDDLE)
        self._pan_gesture.connect("drag-begin", self.on_pan_begin)
        self._pan_gesture.connect("drag-update", self.on_pan_update)
        self._pan_gesture.connect("drag-end", self.on_pan_end)
        self.add_controller(self._pan_gesture)
        self._pan_start = (0.0, 0.0)

        # Track Space key for Space+drag panning
        self._space_pressed = False

        # Add pinch-to-zoom gesture, anchored at the gesture centre.
        self._zoom_gesture = Gtk.GestureZoom.new()
        self._zoom_gesture.connect("begin", self.on_pinch_begin)
        self._zoom_gesture.connect(
            "scale-changed", self.on_pinch_scale_changed
        )
        self._zoom_gesture.connect("end", self.on_pinch_end)
        self._zoom_gesture.connect("cancel", self.on_pinch_cancel)
        self.add_controller(self._zoom_gesture)
        self._pinch_start_zoom: float | None = None

        # Add right-click gesture for context menu
        self._context_menu_gesture = Gtk.GestureClick.new()
        self._context_menu_gesture.set_button(Gdk.BUTTON_SECONDARY)
        self._context_menu_gesture.connect(
            "pressed", self.on_right_click_pressed
        )
        self.add_controller(self._context_menu_gesture)

        # Detect focus loss so an in-progress navigation gesture (e.g.
        # Space held down) can't get stuck if focus moves elsewhere
        # mid-gesture.
        self._focus_controller = Gtk.EventControllerFocus()
        self._focus_controller.connect("leave", self.on_focus_leave)
        self.add_controller(self._focus_controller)

        # Discrete zoom steps and zoom-to-fit are eased in via this
        # animator; continuous gestures update the camera directly.
        self._camera_animator = CameraAnimator(self._camera)
        self._animation_tick_id: int | None = None

        # Trackpad-flick pan inertia state.
        self.pan_inertia_enabled: bool = True
        self._pan_velocity_x: float = 0.0
        self._pan_velocity_y: float = 0.0
        self._inertia_tick_id: int | None = None

        self.connect("unmap", self.on_unmap)

        # This is hacky, but what to do: The EventControllerScroll provides
        # no access to any mouse position, and there is no easy way to
        # get the mouse position in Gtk4. So I have to store it here and
        # track the motion event...
        self._mouse_pos = (0.0, 0.0)

    @property
    def zoom_level(self) -> float:
        """The current zoom level. Use set_zoom to change it."""
        return self._camera.zoom

    @property
    def pan_x_mm(self) -> float:
        """The current pan X offset, in mm. Use set_pan to change it."""
        return self._camera.pan_x_mm

    @property
    def pan_y_mm(self) -> float:
        """The current pan Y offset, in mm. Use set_pan to change it."""
        return self._camera.pan_y_mm

    def set_show_grid(self, show: bool):
        """Sets the visibility of the inner grid lines."""
        self._axis_renderer.show_grid = show
        self.queue_draw()

    def set_show_axis(self, show: bool):
        """Sets the visibility of the outer axis lines and labels."""
        self._axis_renderer.show_axis = show
        self.queue_draw()

    def on_right_click_pressed(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        """
        Placeholder for handling right-clicks. Subclasses should override this
        to implement context menu logic.
        """

    def _update_theme_colors(self) -> None:
        """
        Reads the current theme colors from the widget's style context
        and applies them to the AxisRenderer.
        """
        # Get the foreground color for axes and labels
        fg_rgba = self.get_color()
        self._axis_renderer.set_fg_color(
            (fg_rgba.red, fg_rgba.green, fg_rgba.blue, fg_rgba.alpha)
        )

        # Set the separator color for the grid lines
        self._axis_renderer.set_grid_color(
            (
                fg_rgba.red,
                fg_rgba.green,
                fg_rgba.blue,
                fg_rgba.alpha * 0.3,
            )
        )

    def set_pan(self, pan_x_mm: float, pan_y_mm: float) -> None:
        """Sets the pan position in mm and updates the axis importer."""
        self._camera.set_pan(pan_x_mm, pan_y_mm)
        self._rebuild_view_transform()
        self.queue_draw()

    def set_zoom(self, zoom_level: float) -> None:
        """
        Sets the zoom level and updates the axis importer. The value
        is clamped by the Camera to [MIN_ZOOM_FACTOR,
        MAX_PIXELS_PER_MM's pixel-density bound for the current widget
        size], so clamping cannot be bypassed by calling this
        directly.
        """
        self._update_zoom_bounds()
        self._camera.set_zoom(zoom_level)
        self._rebuild_view_transform()
        self.queue_draw()

    def _update_zoom_bounds(self) -> None:
        """
        Refreshes the Camera's [min_zoom, max_zoom] clamp range from
        the current widget size: MIN_ZOOM_FACTOR as the minimum, and
        the MAX_PIXELS_PER_MM pixel-density ceiling as the maximum.
        """
        base_ppm = self._axis_renderer.get_base_pixels_per_mm(
            self.get_width(), self.get_height()
        )
        max_zoom = (
            self.MAX_PIXELS_PER_MM / base_ppm
            if base_ppm > 0
            else float("inf")
        )
        self._camera.set_zoom_bounds(self.MIN_ZOOM_FACTOR, max_zoom)

    def _update_pan_bounds(self) -> None:
        """
        Refreshes the Camera's pan bounds from the current widget size
        and zoom level, so panning cannot move the bed so far that
        less than MIN_VISIBLE_BED_FRACTION of its width/height remains
        visible. This is the bound used by ``_ease_pan_into_bounds``;
        it does not clamp pan updates directly (the clamp is soft).
        """
        zoom = self.zoom_level
        effective_height = self._axis_renderer.get_effective_height()
        visible_w = self.width_mm / zoom if zoom > 0 else self.width_mm
        visible_h = (
            effective_height / zoom if zoom > 0 else effective_height
        )
        min_visible_w = min(
            self.MIN_VISIBLE_BED_FRACTION * self.width_mm, visible_w
        )
        min_visible_h = min(
            self.MIN_VISIBLE_BED_FRACTION * effective_height, visible_h
        )
        self._camera.set_pan_bounds(
            min_visible_w - visible_w,
            self.width_mm - min_visible_w,
            min_visible_h - visible_h,
            effective_height - min_visible_h,
        )

    def _ease_pan_into_bounds(self) -> bool:
        """
        If the current pan violates the soft "keep at least
        MIN_VISIBLE_BED_FRACTION of the bed visible" clamp, eases it
        back into bounds via the camera animator (reusing Package D3's
        CameraAnimator/tick machinery), leaving zoom unchanged.
        Returns True if an easing animation was started (the pan was
        out of bounds), False if it was already within bounds.
        """
        self._update_pan_bounds()
        clamped_x, clamped_y = self._camera.clamped_pan()
        if (
            abs(clamped_x - self.pan_x_mm) < 1e-9
            and abs(clamped_y - self.pan_y_mm) < 1e-9
        ):
            return False
        self._start_camera_animation(self.zoom_level, clamped_x, clamped_y)
        return True

    def _get_view_layout(
        self,
    ) -> tuple[float, float, float, float, float] | None:
        """
        Returns (base_scale_x, base_scale_y, content_x, content_y,
        content_h) for the current widget size, or None if the widget
        has no usable size yet. These are the same base-scale/content-
        layout values _rebuild_view_transform derives from the
        AxisRenderer, and are what Camera.zoom_about_point needs.
        """
        widget_w, widget_h = self.get_width(), self.get_height()
        if widget_w <= 0 or widget_h <= 0:
            return None
        content_x, content_y, content_w, content_h = (
            self._axis_renderer.get_content_layout(widget_w, widget_h)
        )
        effective_height = self._axis_renderer.get_effective_height()
        base_scale_x = content_w / self.width_mm if self.width_mm > 0 else 1
        base_scale_y = (
            content_h / effective_height if effective_height > 0 else 1
        )
        return base_scale_x, base_scale_y, content_x, content_y, content_h

    def _zoom_about_point_live(
        self, pointer_x_px: float, pointer_y_px: float, new_zoom: float
    ) -> None:
        """
        Applies a zoom about a screen point directly to the live
        camera, with zero lag. Used by continuous gestures (trackpad
        Ctrl+scroll, pinch), which pre-empt any in-progress animation.
        """
        layout = self._get_view_layout()
        if layout is None:
            return
        self._cancel_camera_animation()
        self._update_zoom_bounds()
        zoom, pan_x, pan_y = self._camera.zoom_about_point(
            pointer_x_px, pointer_y_px, new_zoom, *layout
        )
        self._camera.set_zoom(zoom)
        self._camera.set_pan(pan_x, pan_y)
        self._rebuild_view_transform()
        self.queue_draw()

    def _zoom_about_point_animated(
        self, pointer_x_px: float, pointer_y_px: float, new_zoom: float
    ) -> None:
        """
        Eases the camera toward a zoom about a screen point over
        ~180ms. Used by discrete zoom steps (wheel notch, keyboard
        +/-, Ctrl+1).
        """
        layout = self._get_view_layout()
        if layout is None:
            return
        self._update_zoom_bounds()
        zoom, pan_x, pan_y = self._camera.zoom_about_point(
            pointer_x_px, pointer_y_px, new_zoom, *layout
        )
        self._start_camera_animation(zoom, pan_x, pan_y)

    def _zoom_about_viewport_center_animated(self, new_zoom: float) -> None:
        widget_w, widget_h = self.get_width(), self.get_height()
        self._zoom_about_point_animated(
            widget_w / 2.0, widget_h / 2.0, new_zoom
        )

    def zoom_to_fit(self) -> None:
        """
        Eases pan and zoom back to the default fit-to-view state
        (zoom=1.0, pan=(0, 0)) over ~180ms. Unlike reset_view, this
        does not re-derive the surface's mm size/margins from the
        machine, so it's safe to call from a shortcut or double-click
        without disturbing bed geometry.
        """
        self._update_zoom_bounds()
        self._start_camera_animation(1.0, 0.0, 0.0)

    def zoom_to_actual_size(self) -> None:
        """
        Eases zoom to 1.0 (this view's "fit" scale), anchored at the
        viewport centre so whatever is currently centred stays
        centred. Unlike zoom_to_fit, this does not reset pan.
        """
        self._zoom_about_viewport_center_animated(1.0)

    def zoom_in(self) -> None:
        """Zooms in one discrete step, anchored at the viewport centre."""
        self._zoom_about_viewport_center_animated(
            self.zoom_level * DISCRETE_ZOOM_FACTOR
        )

    def zoom_out(self) -> None:
        """Zooms out one discrete step, anchored at the viewport centre."""
        self._zoom_about_viewport_center_animated(
            self.zoom_level / DISCRETE_ZOOM_FACTOR
        )

    def _start_camera_animation(
        self, target_zoom: float, target_pan_x: float, target_pan_y: float
    ) -> None:
        now_ms = self._now_ms()
        self._camera_animator.start(
            target_zoom, target_pan_x, target_pan_y, now_ms
        )
        if self._animation_tick_id is None:
            self._animation_tick_id = self.add_tick_callback(
                self._on_animation_tick
            )

    def _now_ms(self) -> float:
        frame_clock = self.get_frame_clock()
        if frame_clock is not None:
            return frame_clock.get_frame_time() / 1000.0
        return time.monotonic() * 1000.0

    def _on_animation_tick(self, widget, frame_clock) -> bool:
        now_ms = frame_clock.get_frame_time() / 1000.0
        still_running = self._camera_animator.advance(now_ms)
        self._rebuild_view_transform()
        self.queue_draw()
        if still_running:
            return GLib.SOURCE_CONTINUE
        self._animation_tick_id = None
        return GLib.SOURCE_REMOVE

    def _cancel_camera_animation(self) -> None:
        """Stops any in-progress camera animation and removes its tick
        callback, if any."""
        self._camera_animator.stop()
        if self._animation_tick_id is not None:
            self.remove_tick_callback(self._animation_tick_id)
            self._animation_tick_id = None

    def set_size(self, width_mm: float, height_mm: float) -> None:
        """
        Sets the real-world size of the work surface in mm
        and updates related properties.
        """
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.root.set_size(width_mm, height_mm)
        self._axis_renderer.set_width_mm(self.width_mm)
        self._axis_renderer.set_height_mm(self.height_mm)
        self._rebuild_view_transform()
        self.queue_draw()

    def get_size_mm(self) -> tuple[float, float]:
        """Returns the size of the work surface in mm."""
        return self.width_mm, self.height_mm

    def get_view_scale(self) -> tuple[float, float]:
        """
        Returns the current effective pixels-per-millimeter scale of the view,
        taking into account the base scale, zoom, and widget size.
        """
        widget_w, widget_h = self.get_width(), self.get_height()
        if widget_w <= 0 or widget_h <= 0:
            return 1.0, 1.0

        _, _, content_w, content_h = self._axis_renderer.get_content_layout(
            widget_w, widget_h
        )

        effective_height = self._axis_renderer.get_effective_height()
        base_scale_x = content_w / self.width_mm if self.width_mm > 0 else 1
        base_scale_y = (
            content_h / effective_height if effective_height > 0 else 1
        )

        return base_scale_x * self.zoom_level, base_scale_y * self.zoom_level

    def on_motion(self, gesture: Gtk.Gesture, x: float, y: float) -> None:
        self._mouse_pos = x, y

        # Let the base canvas handle hover updates and cursor changes.
        super().on_motion(gesture, x, y)

    def on_scroll(
        self, controller: Gtk.EventControllerScroll, dx: float, dy: float
    ) -> None:
        """
        Dispatches a scroll event to the right navigation gesture:

        - A physical mouse wheel notch (Gdk.ScrollUnit.WHEEL) always
          zooms, by a discrete geometric step (DISCRETE_ZOOM_FACTOR),
          eased in about the pointer.
        - A trackpad's smooth deltas (Gdk.ScrollUnit.SURFACE) zoom
          continuously about the pointer, with zero lag, while
          Ctrl/Cmd is held; otherwise they pan (two-finger scroll),
          also with zero lag.
        """
        logger.debug(f"Scroll event: dx={dx:.2f}, dy={dy:.2f}")
        mouse_x_px, mouse_y_px = self._mouse_pos

        if controller.get_unit() == Gdk.ScrollUnit.WHEEL:
            factor = (
                1.0 / DISCRETE_ZOOM_FACTOR if dy > 0 else DISCRETE_ZOOM_FACTOR
            )
            self._zoom_about_point_animated(
                mouse_x_px, mouse_y_px, self.zoom_level * factor
            )
            return

        if is_primary_modifier(controller.get_current_event_state()):
            factor = math.exp(-dy * TRACKPAD_ZOOM_SENSITIVITY)
            self._zoom_about_point_live(
                mouse_x_px, mouse_y_px, self.zoom_level * factor
            )
            return

        self._pan_by_scroll_delta(dx, dy)

    def _pan_by_scroll_delta(self, dx_px: float, dy_px: float) -> None:
        """
        Pans the live camera by an incremental pixel delta from a
        trackpad's two-finger scroll, with zero lag.
        """
        self._cancel_camera_animation()
        scale_x, scale_y = self.get_view_scale()
        if scale_x <= 0 or scale_y <= 0:
            return
        new_pan_x, new_pan_y = self._camera.pan_by_pixel_offset(
            self.pan_x_mm, self.pan_y_mm, dx_px, dy_px, scale_x, scale_y
        )
        self.set_pan(new_pan_x, new_pan_y)

    def on_scroll_decelerate(
        self, controller: Gtk.EventControllerScroll, vel_x: float, vel_y: float
    ) -> None:
        """
        Starts trackpad-flick pan inertia from the velocity (px/sec)
        GTK reports at the end of a smooth scroll gesture.
        """
        if not self.pan_inertia_enabled:
            self._ease_pan_into_bounds()
            return
        self._cancel_camera_animation()
        # GTK reports px/sec; the inertia decay formula is per-frame.
        # Assume a 60Hz frame clock, matching add_tick_callback's
        # typical cadence.
        self._pan_velocity_x = vel_x / 60.0
        self._pan_velocity_y = vel_y / 60.0
        if self._inertia_tick_id is None:
            self._inertia_tick_id = self.add_tick_callback(
                self._on_inertia_tick
            )

    def _on_inertia_tick(self, widget, frame_clock) -> bool:
        decayed = _decay_pan_velocity(
            self._pan_velocity_x, self._pan_velocity_y
        )
        if decayed is None:
            self._stop_inertia()
            self._ease_pan_into_bounds()
            return GLib.SOURCE_REMOVE
        self._pan_velocity_x, self._pan_velocity_y = decayed
        self._pan_by_scroll_delta(self._pan_velocity_x, self._pan_velocity_y)
        if self._ease_pan_into_bounds():
            # Crossed the soft clamp boundary mid-flight: hand off to
            # the easing animation instead of continuing to coast
            # (and potentially fighting it) further out of bounds.
            self._stop_inertia()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _stop_inertia(self) -> None:
        """Stops any in-progress trackpad-flick pan inertia."""
        self._pan_velocity_x = 0.0
        self._pan_velocity_y = 0.0
        if self._inertia_tick_id is not None:
            self.remove_tick_callback(self._inertia_tick_id)
            self._inertia_tick_id = None

    def on_pinch_begin(self, gesture: Gtk.GestureZoom, sequence) -> None:
        self._pinch_start_zoom = self.zoom_level

    def on_pinch_scale_changed(
        self, gesture: Gtk.GestureZoom, scale: float
    ) -> None:
        """Zooms about the pinch gesture's centre, with zero lag."""
        if self._pinch_start_zoom is None:
            return
        ok, cx, cy = gesture.get_bounding_box_center()
        if not ok:
            return
        self._zoom_about_point_live(cx, cy, self._pinch_start_zoom * scale)

    def on_pinch_end(self, gesture: Gtk.GestureZoom, sequence) -> None:
        self._reset_transient_gesture_state()

    def on_pinch_cancel(self, gesture: Gtk.GestureZoom, sequence) -> None:
        self._reset_transient_gesture_state()

    def _reset_transient_gesture_state(self) -> None:
        """
        Clears per-gesture navigation state that is safe to drop as
        soon as a gesture ends: pinch tracking, and any in-progress
        trackpad-flick inertia. Called on button/gesture release, and
        as part of the wider reset on pointer leave / unmap / focus
        loss. Deliberately does not touch _space_pressed, which is
        tied to the Space key's own state, not to a specific gesture's
        release.
        """
        self._pinch_start_zoom = None
        self._stop_inertia()

    def _reset_all_gesture_state(self) -> None:
        """
        Clears all pan/zoom gesture state, including Space+drag
        tracking. Called on pointer leave, widget unmap, and focus
        loss -- situations where an in-progress gesture can no longer
        receive its normal end/release event and could otherwise be
        left "stuck" (e.g. Space held down forever after the window
        loses focus mid-drag).
        """
        self._space_pressed = False
        self._reset_transient_gesture_state()

    def on_motion_leave(self, controller: Gtk.EventControllerMotion) -> None:
        self._reset_all_gesture_state()
        super().on_motion_leave(controller)

    def on_focus_leave(self, controller: Gtk.EventControllerFocus) -> None:
        self._reset_all_gesture_state()

    def on_unmap(self, widget: Gtk.Widget) -> None:
        self._reset_all_gesture_state()
        self._cancel_camera_animation()

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        # Let the parent Canvas/Gtk.DrawingArea do its work first. This will
        # call self.root.set_size() with pixel dimensions, which we will
        # immediately correct.
        super().do_size_allocate(width, height, baseline)

        # Enforce the correct world (mm) dimensions on the root
        # element, overriding the pixel-based sizing from the parent class.
        if (
            self.root.width != self.width_mm
            or self.root.height != self.height_mm
        ):
            self.root.set_size(self.width_mm, self.height_mm)

        # Rebuild the view transform, which depends on the widget's new pixel
        # dimensions to calculate the correct pan/zoom/scale matrix.
        self._rebuild_view_transform()

    def _rebuild_view_transform(self) -> bool:
        """
        Constructs the world-to-view transformation matrix.
        Returns True if the view scale has changed.
        """
        widget_w, widget_h = self.get_width(), self.get_height()
        if widget_w <= 0 or widget_h <= 0:
            return False

        content_x, content_y, content_w, content_h = (
            self._axis_renderer.get_content_layout(widget_w, widget_h)
        )

        # Base scale to map mm to the unzoomed content area pixels
        # Use effective height to handle rotary mode correctly
        effective_height = self._axis_renderer.get_effective_height()
        scale_x = content_w / self.width_mm if self.width_mm > 0 else 1
        scale_y = content_h / effective_height if effective_height > 0 else 1

        # The sequence of transformations is critical and is applied
        # from right-to-left (bottom to top in this code).

        # 5. Final Offset: Translate the transformed content to its
        #    final position within the widget.
        m_offset = Matrix.translation(content_x, content_y)

        # 4. Zoom: Scale the content around its top-left corner (0,0).
        m_zoom = Matrix.scale(self.zoom_level, self.zoom_level)

        # 3. Y-Axis and Pan transformation
        # We combine pan and the y-flip into one matrix. This ensures panning
        # feels correct regardless of the axis orientation.
        pan_transform = Matrix.translation(-self.pan_x_mm, -self.pan_y_mm)

        # The world is ALWAYS Y-up. The view is ALWAYS Y-down.
        # Therefore, we ALWAYS need to flip the Y-axis. This matrix scales
        # the world to pixels and flips it into the view's coordinate system.
        m_scale = Matrix.translation(0, content_h) @ Matrix.scale(
            scale_x, -scale_y
        )

        # Compose final matrix (read operations from bottom to top):
        # Transformation order:
        #   Pan the world
        #   -> Scale&Flip it
        #   -> Zoom it
        #   -> Offset to final position.
        final_transform = m_offset @ m_zoom @ m_scale @ pan_transform

        # Update the base Canvas's view_transform
        self.view_transform = final_transform

        # Check if the effective scale (pixels-per-mm) has changed. Panning
        # does not change the scale, but zooming and resizing the window do.
        # This prevents expensive re-rendering of buffered elements during
        # panning.
        new_scale_x, new_scale_y = self.get_view_scale()
        scale_changed = (
            abs(new_scale_x - self._last_view_scale_x) > 1e-9
            or abs(new_scale_y - self._last_view_scale_y) > 1e-9
        )

        if scale_changed:
            self._last_view_scale_x = new_scale_x
            self._last_view_scale_y = new_scale_y

        return scale_changed

    def reset_view(self) -> None:
        """
        Resets the view to fit the surface, including a
        full reset of pan and zoom.
        """
        logger.debug("Resetting WorldSurface view.")
        self.set_pan(0.0, 0.0)
        self.set_zoom(1.0)
        self._rebuild_view_transform()
        self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        # Update theme colors right before drawing to catch any live changes.
        self._update_theme_colors()

        # Create a Cairo context for the snapshot
        width, height = self.get_width(), self.get_height()
        ctx = snapshot.append_cairo(Graphene.Rect().init(0, 0, width, height))

        # Draw grid and axes first, in pixel space, before any transformations.
        self._axis_renderer.draw_grid_and_labels(
            ctx, self.view_transform, width, height
        )

        # Now, delegate to the base Canvas's snapshot implementation, which
        # will correctly apply the view_transform and render all elements
        # and selection handles.
        super().do_snapshot(snapshot)

    def on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Handles key press events for the work surface."""
        key_name = Gdk.keyval_name(keyval)
        logger.debug(f"Key pressed: key='{key_name}', state={state}")
        if keyval in (Gdk.KEY_space, Gdk.KEY_KP_Space):
            self._space_pressed = True
            return True
        if keyval == Gdk.KEY_1:
            # Reset pan and zoom with '1'
            self.reset_view()
            return True  # Event handled

        # Propagate to parent Canvas for its default behavior. The base Canvas
        # handles leaving edit mode on Escape.
        return super().on_key_pressed(controller, keyval, keycode, state)

    def on_key_released(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> None:
        """Handles key release events for the work surface."""
        if keyval in (Gdk.KEY_space, Gdk.KEY_KP_Space):
            self._space_pressed = False
            return
        super().on_key_released(controller, keyval, keycode, state)

    def on_button_press(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        """
        Override to suppress element selection when Space is held, and
        to fit the view on a double-click on empty canvas.
        """
        if self._space_pressed:
            self.grab_focus()
            self._cancel_camera_animation()
            self._pan_start = (self.pan_x_mm, self.pan_y_mm)
            return
        if n_press == 2 and not self.edit_context:
            world_x, world_y = self._get_world_coords(x, y)
            self._update_hover_state(world_x, world_y)
            if self._hovered_elem is None:
                self.grab_focus()
                self.zoom_to_fit()
                return
        super().on_button_press(gesture, n_press, x, y)

    def on_click_released(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        """Override to suppress click actions when Space is held."""
        if self._space_pressed:
            return
        super().on_click_released(gesture, n_press, x, y)

    def _pan_by_drag_offset(
        self, offset_x_px: float, offset_y_px: float
    ) -> None:
        """
        Pans the view by a pixel-space drag offset, relative to the pan
        position stored in self._pan_start at the start of the drag.
        Shared by middle-drag (on_pan_update) and Space+drag
        (on_mouse_drag) so their math cannot drift apart.
        """
        widget_w, widget_h = self.get_width(), self.get_height()
        if widget_w <= 0 or widget_h <= 0:
            return

        _, _, content_w, content_h = self._axis_renderer.get_content_layout(
            widget_w, widget_h
        )

        base_scale_x = content_w / self.width_mm if self.width_mm > 0 else 1
        base_scale_y = content_h / self.height_mm if self.height_mm > 0 else 1

        new_pan_x, new_pan_y = self._camera.pan_by_pixel_offset(
            self._pan_start[0],
            self._pan_start[1],
            offset_x_px,
            offset_y_px,
            base_scale_x * self.zoom_level,
            base_scale_y * self.zoom_level,
        )
        self.set_pan(new_pan_x, new_pan_y)

    def on_mouse_drag(
        self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float
    ) -> None:
        """Override to pan instead of selecting when Space is held."""
        if self._space_pressed:
            ok, drag_offset_x, drag_offset_y = gesture.get_offset()
            if not ok:
                return
            self._pan_by_drag_offset(drag_offset_x, drag_offset_y)
            return
        super().on_mouse_drag(gesture, offset_x, offset_y)

    def on_drag_end(
        self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float
    ) -> None:
        """Override to suppress drag end when Space was held."""
        if self._space_pressed:
            self._reset_transient_gesture_state()
            self._ease_pan_into_bounds()
            return
        super().on_drag_end(gesture, offset_x, offset_y)

    def on_pan_begin(
        self, gesture: Gtk.GestureDrag, x: float, y: float
    ) -> None:
        logger.debug(f"Pan begin at ({x:.2f}, {y:.2f})")
        self._cancel_camera_animation()
        self._pan_start = (self.pan_x_mm, self.pan_y_mm)

    def on_pan_update(
        self, gesture: Gtk.GestureDrag, x: float, y: float
    ) -> None:
        # Gtk.GestureDrag.get_offset returns a boolean and populates the
        # provided variables.
        ok, offset_x, offset_y = gesture.get_offset()
        if not ok:
            return

        logger.debug(f"Pan update: offset=({offset_x:.2f}, {offset_y:.2f})")

        # The world-to-view transform is always Y-inverting. To make the
        # content follow the mouse ("natural" panning), the logic must be
        # consistent. A rightward drag (positive offset_x) requires a
        # negative adjustment to pan_x. A downward drag (positive offset_y)
        # requires a positive adjustment to pan_y because of the Y-inversion
        # in the transform matrix. See _pan_by_drag_offset / Camera.
        self._pan_by_drag_offset(offset_x, offset_y)

    def on_pan_end(self, gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        logger.debug(f"Pan end at ({x:.2f}, {y:.2f})")
        self._reset_transient_gesture_state()
        self._ease_pan_into_bounds()
