import logging
import math
import weakref
from typing import TYPE_CHECKING, cast

from ....core.group import Group
from ....core.item import DocItem
from ....core.stock import StockItem
from ....core.workpiece import WorkPiece
from ...canvas.element import CanvasElement
from ...canvas.hittest import STROKE_HIT_DISTANCE
from .group import GroupElement
from .step import StepElement
from .stock import StockElement
from .workpiece import WorkPieceElement

if TYPE_CHECKING:
    from ....core.layer import Layer


logger = logging.getLogger(__name__)


class LayerElement(CanvasElement):
    """
    A non-selectable container that corresponds to a Layer model.
    It creates and manages child elements for WorkPieces, Groups, and Steps.
    """

    def __init__(self, layer: "Layer", **kwargs):
        super().__init__(
            x=0,
            y=0,
            width=0,
            height=0,
            selectable=False,
            background=(0, 0, 0, 0),
            clip=False,
            data=layer,
            **kwargs,
        )
        self.data: Layer = layer
        # Children's hit reach boxes (see _reach_box).
        self._reach_boxes: weakref.WeakKeyDictionary = (
            weakref.WeakKeyDictionary()
        )
        self.data.updated.connect(self.sync_with_model)
        self.data.descendant_added.connect(self.sync_with_model)
        self.data.descendant_removed.connect(self.sync_with_model)
        self.sync_with_model(self.data)

    def remove(self):
        """Disconnects signals before removing the element."""
        self.data.updated.disconnect(self.sync_with_model)
        self.data.descendant_added.disconnect(self.sync_with_model)
        self.data.descendant_removed.disconnect(self.sync_with_model)
        super().remove()

    def set_size(self, width: float, height: float):
        """Sets the size and propagates it to child StepElements."""
        if self.width == width and self.height == height:
            return
        super().set_size(width, height)

        for elem in self.children:
            if isinstance(elem, StepElement):
                elem.set_size(width, height)

    def sort_children_by_z_order(self):
        """Sorts child elements to maintain correct drawing order."""
        model_visual_items = [
            c
            for c in self.data.children
            if isinstance(c, (WorkPiece, Group, StockItem))
        ]
        model_order = {
            id(item): i for i, item in enumerate(model_visual_items)
        }

        def sort_key(element: CanvasElement):
            if isinstance(
                element, (WorkPieceElement, GroupElement, StockElement)
            ):
                return (
                    0,
                    model_order.get(id(element.data), len(model_visual_items)),
                )
            if isinstance(element, StepElement):
                return (1, 0)
            return (2, 0)

        self.children.sort(key=sort_key)

    def get_elem_hit(
        self,
        world_x: float,
        world_y: float,
        selectable: bool = False,
        strokes_only: bool = False,
    ) -> CanvasElement | None:
        """A hidden layer is inert: nothing on it can be hit."""
        if not self.visible:
            return None
        return super().get_elem_hit(world_x, world_y, selectable, strokes_only)

    def _get_child_hit(
        self,
        world_x: float,
        world_y: float,
        selectable: bool,
        strokes_only: bool,
    ) -> CanvasElement | None:
        """
        Tests only the children whose reach holds the point: their box
        and their own children's, grown by the stroke hit distance. A
        pointer motion over hundreds of pieces then runs the stroke,
        inside and pixel tests of a few, not of every one.
        """
        reach = math.inf
        if self.canvas:
            scale = min(self.canvas.view_transform.get_abs_scale())
            if scale > 0:
                reach = (STROKE_HIT_DISTANCE + 1.0) / scale
        for child in reversed(self.children):
            x0, y0, x1, y1 = self._reach_box(child)
            if (
                x0 - reach <= world_x <= x1 + reach
                and y0 - reach <= world_y <= y1 + reach
            ):
                hit = child.get_elem_hit(
                    world_x, world_y, selectable, strokes_only
                )
                if hit:
                    return hit
        return None

    def _reach_box(self, child: CanvasElement):
        """
        The world box of a child and its children, cached until the
        child's world transform (a new matrix whenever it changes), its
        size or its number of children changes.
        """
        key = (child.get_world_transform(), child.width, child.height)
        count = len(child.children)
        cached = self._reach_boxes.get(child)
        if (
            cached
            and cached[0][0] is key[0]
            and cached[0][1:] == key[1:]
            and cached[1] == count
        ):
            return cached[2]
        boxes = [child.get_world_bounding_box()] + [
            c.get_world_bounding_box() for c in child.children
        ]
        box = (
            min(x for x, _y, _w, _h in boxes),
            min(y for _x, y, _w, _h in boxes),
            max(x + w for x, _y, w, _h in boxes),
            max(y + h for _x, y, _w, h in boxes),
        )
        self._reach_boxes[child] = (key, count, box)
        return box

    def _drop_from_selection(self):
        """Removes this layer's elements from the canvas selection."""
        assert self.canvas
        editing = self.canvas.edit_context
        if editing and editing in self.get_all_children_recursive():
            self.canvas.leave_edit_mode()
        if any(self.get_selected()):
            self.unselect_all()
            self.canvas._finalize_selection_state()

    def sync_with_model(
        self,
        sender,
        origin: DocItem | None = None,
        parent_of_origin: DocItem | None = None,
        **kwargs,
    ):
        """
        Reconciles all child elements with the state of the Layer model.
        """
        if not self.data or not self.canvas:
            return

        logger.debug(
            f"LayerElement for '{self.data.name}': sync_with_model is"
            f" executing, called by {origin or sender}."
        )
        self.set_visible(self.data.visible)
        from ..surface import WorkSurface

        work_surface = cast(WorkSurface, self.canvas)

        # Reconcile Visual Elements (WorkPieces, Groups, StockItems)
        model_items = {
            c
            for c in self.data.children
            if isinstance(c, (WorkPiece, Group, StockItem))
        }
        current_visual_elements = [
            elem
            for elem in self.children
            if isinstance(elem, (WorkPieceElement, GroupElement, StockElement))
        ]

        # Remove elements for items no longer in the layer
        for elem in current_visual_elements[:]:
            if elem.data not in model_items:
                logger.debug(f"Removing visual element: {elem}")
                elem.remove()

        # Add elements for new items in the layer.
        current_item_data = {elem.data for elem in self.children}
        items_to_add = model_items - current_item_data
        for item_data in items_to_add:
            new_elem = None
            if isinstance(item_data, WorkPiece):
                new_elem = WorkPieceElement(
                    workpiece=item_data,
                    view_manager=work_surface.editor.view_manager,
                    canvas=self.canvas,
                    selectable=self.data.visible,
                )
                new_elem.set_base_image_visible(
                    work_surface.are_workpieces_visible()
                )
            elif isinstance(item_data, Group):
                new_elem = GroupElement(
                    group=item_data,
                    canvas=self.canvas,
                    selectable=self.data.visible,
                )
            elif isinstance(item_data, StockItem):
                new_elem = StockElement(
                    stock_item=item_data,
                    canvas=self.canvas,
                    # Stock is potentially selectable, but its get_elem_hit
                    # method will make the final decision based on layer state.
                    selectable=True,
                )

            if new_elem:
                self.add(new_elem)

        # A hidden layer is inert: its shapes are not selectable, and
        # hiding it drops them from the selection.
        for elem in self.children:
            if isinstance(elem, (WorkPieceElement, GroupElement)):
                elem.selectable = self.data.visible
        if not self.data.visible:
            self._drop_from_selection()

        if self.data.workflow is None:
            return  # layers without workflow

        # Reconcile StepElements (Lifecycle Managers)
        current_step_elements = [
            elem for elem in self.children if isinstance(elem, StepElement)
        ]
        workpiece_views = [
            elem
            for elem in self.children
            if isinstance(elem, WorkPieceElement)
        ]
        model_steps = set(self.data.workflow.steps)

        # Remove StepElements for steps that are no longer in the model
        for elem in current_step_elements:
            if elem.data not in model_steps:
                removed_step_uid = elem.data.uid
                logger.debug(
                    "LayerElement detected removal of step "
                    f"'{elem.data.name}'. "
                    f"Cleaning up visuals for UID {removed_step_uid}."
                )
                # Instruct all workpiece views in this layer to clear the
                # surface
                for wp_view in workpiece_views:
                    wp_view.clear_ops_surface(removed_step_uid)
                elem.remove()

        # Add StepElements for new steps.
        current_step_data = {
            elem.data
            for elem in self.children
            if isinstance(elem, StepElement)
        }
        steps_to_add = model_steps - current_step_data
        for step_data in steps_to_add:
            step_elem = StepElement(
                step=step_data,
                pipeline=work_surface.editor.pipeline,
                canvas=self.canvas,
            )
            self.add(step_elem)

        # After all children are added/removed, we ensure every StepElement
        # broadcasts its current visibility to every WorkPieceElement. This
        # guarantees that newly created elements get the correct initial state.
        for elem in self.children:
            if isinstance(elem, StepElement):
                elem._update_sibling_ops_visibility()

        self.sort_children_by_z_order()
        self.canvas.queue_draw()
