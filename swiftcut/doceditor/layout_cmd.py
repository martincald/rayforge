from __future__ import annotations

import logging
from gettext import gettext as _
from typing import TYPE_CHECKING

from ..core.item import DocItem
from ..core.undo import ChangePropertyCommand
from ..shared.placement import arrange
from .layout import (
    BboxAlignBottomStrategy,
    BboxAlignCenterStrategy,
    BboxAlignLeftStrategy,
    BboxAlignMiddleStrategy,
    BboxAlignRightStrategy,
    BboxAlignTopStrategy,
    LayoutStrategy,
    NestLayoutStrategy,
    PositionAtStrategy,
    SpreadHorizontallyStrategy,
    SpreadVerticallyStrategy,
)

if TYPE_CHECKING:
    from raygeo.geo import Matrix

    from ..shared.tasker.manager import TaskManager
    from ..shared.tasker.task import Task
    from .editor import DocEditor

logger = logging.getLogger(__name__)

#: The key of the task an Auto Layout runs as.
AUTO_LAYOUT_KEY = "auto-layout"


class LayoutCmd:
    """Handles alignment, distribution, and automatic layout of items."""

    def __init__(self, editor: DocEditor, task_manager: TaskManager):
        self._editor = editor
        self._task_manager = task_manager

    def execute_layout(
        self,
        strategy: LayoutStrategy,
        transaction_name: str,
        use_async: bool = False,
    ):
        """
        Execute a layout strategy with undo/redo support.

        Configures and launches a background layout task. The actual model
        mutation happens in the `when_done` callback, which is guaranteed
        to run on the main GTK thread.

        Args:
            strategy: The layout strategy to execute.
            transaction_name: Name for the undo transaction.
            use_async: If True, use async calculation for the strategy.
        """
        # Define the handler that will receive error signals from the strategy.
        def on_error_reported(sender, message: str):
            """
            Receives an error message from the strategy (from a background
            thread) and safely schedules a UI notification on the main thread.
            """
            # Wrap the call in a lambda to ensure the keyword argument is
            # passed correctly by GLib.idle_add.
            self._task_manager.schedule_on_main_thread(
                self._editor.notification_requested.send, self, message=message
            )

        # Connect the handler before running the task.
        strategy.error_reported.connect(on_error_reported)

        def when_done(task: Task):
            """
            This callback runs on the main thread after the task finishes.
            It disconnects the signal handler and safely applies the
            calculated changes to the document.
            """
            # Disconnect the handler to prevent potential memory leaks.
            strategy.error_reported.disconnect(on_error_reported)

            if task.get_status() != "completed":
                logger.error(
                    "Layout task '%s' did not complete successfully. "
                    "Status: %s",
                    transaction_name,
                    task.get_status(),
                )
                return

            # The result of the task is the dictionary of transformation
            # deltas.
            self._apply_deltas(task.result(), transaction_name)

        # This simple coroutine just runs the calculation in the background
        # and returns the result.
        async def layout_coro(context):
            if use_async:
                return await strategy.calculate_deltas_async(
                    context, self._task_manager
                )
            return strategy.calculate_deltas(context)

        # Launch the coroutine and attach the main-thread callback.
        self._task_manager.add_coroutine(
            layout_coro,
            when_done=when_done,
            key=f"layout-{transaction_name}",  # key to prevent concurrent runs
        )

    def _apply_deltas(
        self, deltas: dict[DocItem, Matrix], transaction_name: str
    ):
        """Applies the deltas (`delta @ item.matrix`) as one undo step."""
        if not deltas:
            return  # No changes to apply

        with self._editor.history_manager.transaction(transaction_name) as t:
            for item, delta_matrix in deltas.items():
                old_matrix = item.matrix.copy()
                new_matrix = delta_matrix @ old_matrix
                cmd = ChangePropertyCommand(
                    target=item,
                    property_name="matrix",
                    new_value=new_matrix,
                    old_value=old_matrix,
                )
                t.execute(cmd)

    def center_horizontally(
        self, selected_items: list[DocItem], surface_width_mm: float
    ):
        """Action handler for centering selected items horizontally."""
        if not selected_items:
            return

        strategy = BboxAlignCenterStrategy(
            selected_items, surface_width_mm=surface_width_mm
        )
        self.execute_layout(strategy, _("Center Horizontally"))

    def center_vertically(
        self, selected_items: list[DocItem], surface_height_mm: float
    ):
        """Action handler for centering selected items vertically."""
        if not selected_items:
            return

        strategy = BboxAlignMiddleStrategy(
            selected_items, surface_height_mm=surface_height_mm
        )
        self.execute_layout(strategy, _("Center Vertically"))

    def align_left(self, selected_items: list[DocItem]):
        """Action handler for aligning selected items to the left."""
        if not selected_items:
            return

        strategy = BboxAlignLeftStrategy(selected_items)
        self.execute_layout(strategy, _("Align Left"))

    def align_right(
        self, selected_items: list[DocItem], surface_width_mm: float
    ):
        """Action handler for aligning selected items to the right."""
        if not selected_items:
            return

        strategy = BboxAlignRightStrategy(
            selected_items, surface_width_mm=surface_width_mm
        )
        self.execute_layout(strategy, _("Align Right"))

    def align_top(
        self, selected_items: list[DocItem], surface_height_mm: float
    ):
        """Action handler for aligning selected items to the top."""
        if not selected_items:
            return

        strategy = BboxAlignTopStrategy(
            selected_items, surface_height_mm=surface_height_mm
        )
        self.execute_layout(strategy, _("Align Top"))

    def align_bottom(self, selected_items: list[DocItem]):
        """Action handler for aligning selected items to the bottom."""
        if not selected_items:
            return

        strategy = BboxAlignBottomStrategy(selected_items)
        self.execute_layout(strategy, _("Align Bottom"))

    def spread_horizontally(self, selected_items: list[DocItem]):
        """Action handler for spreading selected items horizontally."""
        if not selected_items:
            return

        strategy = SpreadHorizontallyStrategy(selected_items)
        self.execute_layout(strategy, _("Spread Horizontally"))

    def spread_vertically(self, selected_items: list[DocItem]):
        """Action handler for spreading selected items vertically."""
        if not selected_items:
            return

        strategy = SpreadVerticallyStrategy(selected_items)
        self.execute_layout(strategy, _("Spread Vertically"))

    def position_at(
        self, selected_items: list[DocItem], position_mm: tuple[float, float]
    ):
        """Action handler for positioning the selection's center at a point."""
        if not selected_items:
            return

        strategy = PositionAtStrategy(
            items=selected_items, position_mm=position_mm
        )
        self.execute_layout(strategy, _("Position at Point"))

    def layout_pixel_perfect(self, selected_items: list[DocItem]):
        """
        Action handler for Auto Layout on true outlines. The document
        is read here; the layout is worked out in a worker process, as
        the task AUTO_LAYOUT_KEY (with progress, and cancelling it
        changes nothing), and applied on the main thread as one undo
        step, unless the document changed meanwhile.
        """
        items_to_layout = self.get_items_to_layout(selected_items)

        if not items_to_layout:
            return

        strategy = NestLayoutStrategy(items=items_to_layout)
        args = strategy.arrange_args()
        if args is None:
            self._editor.notification_requested.send(
                self,
                message=_(
                    "Auto Layout needs a stock or a machine bed to lay "
                    "out on."
                ),
            )
            return

        def on_error_reported(sender, message: str):
            self._editor.notification_requested.send(self, message=message)

        def when_done(task: Task):
            # Cancelled: nothing changes. Failed: the task manager
            # logged it.
            if task.get_status() != "completed":
                return
            # Worked out on the document as it was read: one that has
            # changed since may not have room where the result says.
            if self._editor.doc is not strategy.doc or strategy.changed():
                self._editor.notification_requested.send(
                    self,
                    message=_(
                        "The document changed during Auto Layout; "
                        "nothing was moved."
                    ),
                )
                return
            strategy.error_reported.connect(on_error_reported)
            deltas = strategy.deltas(task.result())
            self._apply_deltas(deltas, _("Auto Layout"))

        self._task_manager.run_process(
            arrange, *args, key=AUTO_LAYOUT_KEY, when_done=when_done
        )

    def get_items_to_layout(
        self, selected_items: list[DocItem]
    ) -> list[DocItem]:
        """Determine items to layout based on selection context."""
        if not selected_items:
            # If nothing is selected, get all top-level content items from
            # the current active layer only.
            items_to_layout = []
            active_layer = self._editor.doc.active_layer
            if active_layer:
                items_to_layout.extend(active_layer.get_content_items())
        else:
            # For any selection, only pack the top-level selected items.
            # E.g., if a group and its child are both selected, only pack the
            # group.
            items_to_layout = []
            selected_set = set(selected_items)
            for item in selected_items:
                has_selected_ancestor = False
                p = item.parent
                while p:
                    if p in selected_set:
                        has_selected_ancestor = True
                        break
                    p = p.parent
                if not has_selected_ancestor:
                    items_to_layout.append(item)

        return items_to_layout
