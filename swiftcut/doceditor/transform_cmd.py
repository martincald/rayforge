from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from gettext import gettext as _
from typing import TYPE_CHECKING

from raygeo.geo import Matrix

from ..context import get_context
from ..core.bed_bounds import bed_rect, clamp_offset, fits
from ..core.item import DocItem
from ..core.undo import ChangePropertyCommand

if TYPE_CHECKING:
    from .editor import DocEditor

logger = logging.getLogger(__name__)


class TransformCmd:
    """Handles undoable transformations of document items."""

    def __init__(self, editor: DocEditor):
        self._editor = editor

    def create_transform_transaction(
        self,
        changes: list[tuple[DocItem, Matrix, Matrix]],
        propagate: bool = True,
    ):
        """
        Creates a single, undoable transaction for a list of matrix changes
        that have already been calculated.

        Args:
            changes: A list of tuples, where each tuple contains
                (DocItem_to_change, old_matrix, new_matrix).
            propagate: Also moves the other items of the changed items'
                groups (see _followers).
        """
        history_manager = self._editor.history_manager
        if not changes:
            return
        if propagate:
            changes = changes + self._followers(changes)

        logger.debug(
            f"Creating transform transaction for {len(changes)} item(s)."
        )

        with history_manager.transaction(_("Transform item(s)")) as t:
            for doc_item, old_matrix, new_matrix in changes:
                if old_matrix.is_close(new_matrix):
                    continue

                cmd = ChangePropertyCommand(
                    target=doc_item,
                    property_name="matrix",
                    new_value=new_matrix,
                    old_value=old_matrix,
                )
                t.execute(cmd)

    def _followers(
        self, changes: list[tuple[DocItem, Matrix, Matrix]]
    ) -> list[tuple[DocItem, Matrix, Matrix]]:
        """
        The changes that carry the changed items' groups along: every
        other item of each outermost group a changed item is in (one on
        a hidden layer, say) gets the world move of the first changed
        item of that group.
        """
        groups = self._editor.doc.item_groups
        changed = {item.uid for item, _old, _new in changes}
        done: set[str] = set()
        followers = []
        for item, old_matrix, new_matrix in changes:
            top = groups.top_of(item.uid)
            if top is None or top.uid in done:
                continue
            done.add(top.uid)
            parent_world = (
                item.parent.get_world_transform()
                if item.parent
                else Matrix.identity()
            )
            delta = (parent_world @ new_matrix) @ (
                parent_world @ old_matrix
            ).invert()
            for member in groups.items_of(top):
                if member.uid in changed:
                    continue
                new_world = delta @ member.get_world_transform()
                followers.append(
                    (
                        member,
                        member.matrix.copy(),
                        self._world_to_local_matrix(member, new_world),
                    )
                )
        return followers

    def _closure(self, items: list[DocItem], propagate: bool) -> list[DocItem]:
        """The items, then (with propagate) the rest of their groups'
        items: what moves when they move."""
        if not propagate:
            return items
        return self._editor.doc.item_groups.closure(items)

    def _with_groups(
        self, items: list[DocItem], propagate: bool
    ) -> Iterator[tuple[DocItem, list[DocItem]]]:
        """Each item with what moves with it, the item first: its
        group's items (with propagate), or the item alone. An item that
        moves with an earlier one's group is left out, so the first of
        a group's items in the list is its anchor."""
        groups = self._editor.doc.item_groups
        done: set[str] = set()
        for item in items:
            if item.uid in done:
                continue
            if propagate and groups.top_of(item.uid) is not None:
                moved = groups.closure([item])
            else:
                moved = [item]
            done.update(member.uid for member in moved)
            yield item, moved

    @staticmethod
    def group_bbox_world(
        items: list[DocItem],
    ) -> tuple[float, float, float, float]:
        """Returns ``(min_x, min_y, max_x, max_y)`` of the items' combined
        axis-aligned bounding box in world space.

        A DocItem's local coordinate space is the unit square
        ``[0, 1] x [0, 1]``; the item's world transform encodes its size
        as a scale factor, so we sample the four unit-square corners and
        transform them into world space.
        """
        min_x, max_x = float("inf"), float("-inf")
        min_y, max_y = float("inf"), float("-inf")
        for item in items:
            world_transform = item.get_world_transform()
            for lx, ly in [(0, 0), (1, 0), (1, 1), (0, 1)]:
                wx, wy = world_transform.transform_point((lx, ly))
                min_x, max_x = min(min_x, wx), max(max_x, wx)
                min_y, max_y = min(min_y, wy), max(max_y, wy)
        return min_x, min_y, max_x, max_y

    @classmethod
    def group_center_world(cls, items: list[DocItem]) -> tuple[float, float]:
        """World-space centre of the items' combined bounding box."""
        min_x, min_y, max_x, max_y = cls.group_bbox_world(items)
        return (min_x + max_x) / 2.0, (min_y + max_y) / 2.0

    @staticmethod
    def _world_to_local_matrix(
        item: DocItem, world_transform: Matrix
    ) -> Matrix:
        """Convert a world-space transform back to the item's local matrix
        by cancelling out the parent's world transform."""
        if item.parent:
            parent_world = item.parent.get_world_transform()
            try:
                return parent_world.invert() @ world_transform
            except ValueError:
                return item.matrix.copy()
        return world_transform

    def bed_move(
        self, items: list[DocItem], dx: float, dy: float
    ) -> tuple[float, float]:
        """The world move (dx, dy) of the items, cut so their combined
        world box stays inside the bed; a box already outside comes
        back in."""
        machine = get_context().machine
        if not machine:
            return dx, dy
        min_x, min_y, max_x, max_y = self.group_bbox_world(items)
        off_x, off_y = clamp_offset(
            (min_x + dx, min_y + dy, max_x - min_x, max_y - min_y),
            bed_rect(machine),
        )
        return dx + off_x, dy + off_y

    def _into_bed(
        self, items: list[DocItem], old_matrices: list[Matrix]
    ) -> None:
        """Moves items, already at their new matrices, so their combined
        world box lies inside the bed; back to their old matrices when
        that box is larger than the bed."""
        machine = get_context().machine
        if not machine:
            return
        bed = bed_rect(machine)
        min_x, min_y, max_x, max_y = self.group_bbox_world(items)
        box = (min_x, min_y, max_x - min_x, max_y - min_y)
        if not fits(box[2:], bed):
            for item, old_matrix in zip(items, old_matrices):
                item.matrix = old_matrix
            return
        dx, dy = clamp_offset(box, bed)
        if not (dx or dy):
            return
        shift = Matrix.translation(dx, dy)
        for item in items:
            item.matrix = self._world_to_local_matrix(
                item, shift @ item.get_world_transform()
            )

    @staticmethod
    def _record(t, items: list[DocItem], old_matrices: list[Matrix]):
        """Records each item's change from its old matrix to its current
        one in the transaction *t*."""
        for item, old_matrix in zip(items, old_matrices):
            new_matrix = item.matrix.copy()
            if old_matrix.is_close(new_matrix):
                item.matrix = old_matrix
                continue
            cmd = ChangePropertyCommand(
                target=item,
                property_name="matrix",
                new_value=new_matrix,
                old_value=old_matrix,
            )
            t.execute(cmd)

    def nudge_items(
        self,
        items: list[DocItem],
        dx_mm: float,
        dy_mm: float,
        propagate: bool = True,
    ):
        """
        Moves a list of DocItems by a given delta in world coordinates,
        creating a single undoable transaction for the operation.

        Args:
            items: The list of DocItems to move.
            dx_mm: The distance to move along the X-axis in millimeters.
            dy_mm: The distance to move along the Y-axis in millimeters.
            propagate: Also moves the rest of the items' groups.
        """
        history_manager = self._editor.history_manager
        if not items:
            return
        items = self._closure(items, propagate)
        dx_mm, dy_mm = self.bed_move(items, dx_mm, dy_mm)
        if dx_mm == 0.0 and dy_mm == 0.0:
            return

        with history_manager.transaction(_("Move item(s)")) as t:
            for item in items:
                old_matrix = item.matrix.copy()
                # Nudge must be pre-multiplied to apply the translation in
                # world space, not local space.
                delta = Matrix.translation(dx_mm, dy_mm)
                new_matrix = delta @ old_matrix

                if old_matrix.is_close(new_matrix):
                    continue

                cmd = ChangePropertyCommand(
                    target=item,
                    property_name="matrix",
                    new_value=new_matrix,
                    old_value=old_matrix,
                )
                t.execute(cmd)

    def flip_horizontal(self, items: list[DocItem], propagate: bool = True):
        """
        Flips a list of DocItems horizontally (mirrors along the Y-axis),
        creating a single undoable transaction for the operation.

        Args:
            items: The list of DocItems to flip horizontally.
            propagate: Flips each item's group as one, about the
                group's centre (see _flip).
        """
        self._flip(
            items, Matrix.flip_horizontal, _("Flip Horizontal"), propagate
        )

    def flip_vertical(self, items: list[DocItem], propagate: bool = True):
        """
        Flips a list of DocItems vertically (mirrors along the X-axis),
        creating a single undoable transaction for the operation.

        Args:
            items: The list of DocItems to flip vertically.
            propagate: Flips each item's group as one, about the
                group's centre (see _flip).
        """
        self._flip(items, Matrix.flip_vertical, _("Flip Vertical"), propagate)

    def _flip(
        self,
        items: list[DocItem],
        flip: Callable[..., Matrix],
        name: str,
        propagate: bool,
    ):
        """
        Mirrors each item about its own centre in the world, as one undo
        step named *name*; *flip* makes the mirror matrix about a centre.
        With propagate, an item in a group and the rest of the group's
        items (see _with_groups) are mirrored as one, about the centre
        of their combined box.
        """
        history_manager = self._editor.history_manager
        if not items:
            return

        with history_manager.transaction(name) as t:
            for _item, moved in self._with_groups(items, propagate):
                flip_matrix = flip(center=self.group_center_world(moved))
                for member in moved:
                    old_matrix = member.matrix.copy()
                    new_matrix = self._world_to_local_matrix(
                        member, flip_matrix @ member.get_world_transform()
                    )

                    if old_matrix.is_close(new_matrix):
                        continue

                    cmd = ChangePropertyCommand(
                        target=member,
                        property_name="matrix",
                        new_value=new_matrix,
                        old_value=old_matrix,
                    )
                    t.execute(cmd)

    def set_position(
        self,
        items: list[DocItem],
        x: float,
        y: float,
        propagate: bool = True,
    ):
        """
        Sets the position of **every** item individually using machine
        coordinates.  Each item's top-left corner is moved to the world
        position derived from ``(x, y)`` and that item's own size, so
        items with different sizes land at different world positions.

        Args:
            items: List of items to move.
            x: Target X position in machine coordinates.
            y: Target Y position in machine coordinates.
            propagate: The rest of an item's group moves by the item's
                delta; of several items of one group, the first one is
                placed.
        """
        history_manager = self._editor.history_manager
        if not items:
            return

        machine = get_context().machine

        with history_manager.transaction(_("Move item(s)")) as t:
            for item, moved in self._with_groups(items, propagate):
                # Convert target Machine Coordinate to World Coordinate
                # We need the item's size for correct conversion if origin is
                # right/top.
                size_world = item.size

                if machine:
                    x_world, y_world = machine.panel.machine_item_to_world(
                        (x, y), size_world
                    )
                else:
                    # Fallback to direct mapping if no machine context
                    x_world, y_world = x, y

                current_pos = item.pos
                dx, dy = self.bed_move(
                    moved, x_world - current_pos[0], y_world - current_pos[1]
                )

                for member in moved:
                    old_matrix = member.matrix.copy()
                    # Apply translation to matrix
                    new_matrix = Matrix.translation(dx, dy) @ old_matrix

                    if old_matrix.is_close(new_matrix):
                        continue

                    cmd = ChangePropertyCommand(
                        target=member,
                        property_name="matrix",
                        new_value=new_matrix,
                        old_value=old_matrix,
                    )
                    t.execute(cmd)

    def set_angle(
        self, items: list[DocItem], angle: float, propagate: bool = True
    ):
        """Sets **every** item's local rotation angle to *angle* degrees,
        preserving each item's own world-space center. With propagate,
        an item in a group turns its group about the group's centre
        instead (see set_angle_group, the item the anchor)."""
        history_manager = self._editor.history_manager
        if not items:
            return

        with history_manager.transaction(_("Change item angle")) as t:
            for item, moved in self._with_groups(items, propagate):
                if len(moved) > 1:
                    self._turn_group(t, moved, angle)
                    continue
                old_matrix = item.matrix.copy()
                item.angle = angle
                self._into_bed([item], [old_matrix])
                new_matrix = item.matrix.copy()

                if old_matrix.is_close(new_matrix):
                    continue

                cmd = ChangePropertyCommand(
                    target=item,
                    property_name="matrix",
                    new_value=new_matrix,
                    old_value=old_matrix,
                )
                t.execute(cmd)

    def set_shear(
        self, items: list[DocItem], shear: float, propagate: bool = True
    ):
        """Sets **every** item's local shear angle to *shear* degrees,
        preserving each item's own world-space center. With propagate,
        an item in a group shears its group instead (see
        set_shear_group, the item the anchor)."""
        history_manager = self._editor.history_manager
        if not items:
            return

        with history_manager.transaction(_("Change item shear")) as t:
            for item, moved in self._with_groups(items, propagate):
                if len(moved) > 1:
                    self._shear_group(t, moved, shear)
                    continue
                old_matrix = item.matrix.copy()
                item.shear = shear
                self._into_bed([item], [old_matrix])
                new_matrix = item.matrix.copy()

                if old_matrix.is_close(new_matrix):
                    continue

                cmd = ChangePropertyCommand(
                    target=item,
                    property_name="matrix",
                    new_value=new_matrix,
                    old_value=old_matrix,
                )
                t.execute(cmd)

    def set_size(
        self,
        items: list[DocItem],
        width: float | None = None,
        height: float | None = None,
        fixed_ratio: bool = False,
        sizes: list[tuple[float, float]] | None = None,
        propagate: bool = True,
    ):
        """Sets the size of each item individually.

        Args:
            items: The list of DocItems to resize.
            width: The target width. Ignored if ``sizes`` is provided.
            height: The target height. Ignored if ``sizes`` is provided.
            fixed_ratio: If True, calculates the missing dimension based on
                         aspect ratio if one dimension is None.
            sizes: A list of ``(width, height)`` tuples, one per item.
                   If provided this takes precedence over ``width``/``height``.
            propagate: An item in a group scales its group about the
                group's centre instead, by the factors that give the
                item its new size (along the world axes, as
                set_size_group does).
        """
        history_manager = self._editor.history_manager
        if not items:
            return

        if sizes is not None and len(sizes) != len(items):
            logger.error(
                "Length of sizes list must match length of items list."
            )
            return

        def _calculate_missing_dim(
            item: DocItem, w: float | None, h: float | None
        ) -> tuple[float, float]:
            """Calculates final width and height handling aspect ratio."""
            current_w, current_h = item.size
            final_w = w if w is not None else current_w
            final_h = h if h is not None else current_h

            if fixed_ratio:
                aspect_ratio = item.get_current_aspect_ratio()
                if aspect_ratio:
                    if w is not None and h is None:
                        final_h = final_w / aspect_ratio
                    elif h is not None and w is None:
                        final_w = final_h * aspect_ratio

            return final_w, final_h

        targets = dict(zip(items, sizes)) if sizes is not None else {}
        with history_manager.transaction(_("Resize item(s)")) as t:
            for item, moved in self._with_groups(items, propagate):
                if sizes is not None:
                    new_width, new_height = targets[item]
                else:
                    new_width, new_height = _calculate_missing_dim(
                        item, width, height
                    )

                if len(moved) > 1:
                    # A side too thin to measure keeps its length.
                    cur_w, cur_h = item.size
                    self._scale_group(
                        t,
                        moved,
                        new_width / cur_w if cur_w > 1e-9 else 1.0,
                        new_height / cur_h if cur_h > 1e-9 else 1.0,
                    )
                    continue

                old_matrix = item.matrix.copy()
                # The set_size method will rebuild the matrix,
                # preserving pos/angle
                item.set_size(new_width, new_height)
                self._into_bed([item], [old_matrix])
                new_matrix = item.matrix.copy()

                if old_matrix.is_close(new_matrix):
                    continue

                cmd = ChangePropertyCommand(
                    target=item,
                    property_name="matrix",
                    new_value=new_matrix,
                    old_value=old_matrix,
                )
                t.execute(cmd)

    def set_position_group(
        self,
        items: list[DocItem],
        x: float,
        y: float,
        propagate: bool = True,
    ):
        """Moves the selection so its **combined bounding box** reaches
        the given target in machine coordinates.

        The ``(x, y)`` target is the desired machine-space position of the
        bounding-box corner that the machine origin refers to (top-left,
        top-right, bottom-left or bottom-right).  The conversion uses the
        combined size of all items, so the whole group lands exactly at
        the target. With propagate the selection is its items' closure
        (see _closure).
        """
        history_manager = self._editor.history_manager
        if not items:
            return
        items = self._closure(items, propagate)

        bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = self.group_bbox_world(
            items
        )
        group_size = (
            bbox_max_x - bbox_min_x,
            bbox_max_y - bbox_min_y,
        )

        machine = get_context().machine
        if machine:
            target_world = machine.panel.machine_item_to_world(
                (x, y), group_size
            )
        else:
            target_world = (x, y)

        dx, dy = self.bed_move(
            items, target_world[0] - bbox_min_x, target_world[1] - bbox_min_y
        )

        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return

        with history_manager.transaction(_("Move item(s)")) as t:
            for item in items:
                old_matrix = item.matrix.copy()
                new_matrix = Matrix.translation(dx, dy) @ old_matrix

                if old_matrix.is_close(new_matrix):
                    continue

                cmd = ChangePropertyCommand(
                    target=item,
                    property_name="matrix",
                    new_value=new_matrix,
                    old_value=old_matrix,
                )
                t.execute(cmd)

    def set_angle_group(
        self, items: list[DocItem], angle: float, propagate: bool = True
    ):
        """Rotates the whole selection so the anchor item (``items[0]``)
        reaches *angle* degrees.

        The rotation is applied as a world-space delta around the group's
        bounding-box centre.  Every item receives the same delta, so
        relative positions are preserved and the group rotates as a whole.
        With propagate the selection is its items' closure (see
        _closure).
        """
        history_manager = self._editor.history_manager
        if not items:
            return
        items = self._closure(items, propagate)

        with history_manager.transaction(_("Change item angle")) as t:
            self._turn_group(t, items, angle)

    def _turn_group(self, t, items: list[DocItem], angle: float):
        """set_angle_group's turn, recorded in the transaction *t*."""
        anchor = items[0]
        delta_angle = angle - anchor.angle
        if abs(delta_angle - round(delta_angle / 360.0) * 360.0) < 1e-9:
            return

        center = self.group_center_world(items)

        old_matrices = [item.matrix.copy() for item in items]
        for item in items:
            world_transform_old = item.get_world_transform()
            rotate_transform_world = Matrix.rotation(
                delta_angle, center=center
            )
            world_transform_new = rotate_transform_world @ world_transform_old

            item.matrix = self._world_to_local_matrix(
                item, world_transform_new
            )
        self._into_bed(items, old_matrices)
        self._record(t, items, old_matrices)

    def set_shear_group(
        self, items: list[DocItem], shear: float, propagate: bool = True
    ):
        """Shears the whole selection so the anchor item (``items[0]``)
        reaches *shear* degrees.

        The shear delta is applied to each item's local matrix rather than
        as a world-space shear around the group centre.  This ensures the
        operation is stateless and idempotent: shear does not commute with
        translation, so composing world-space deltas would accumulate
        decomposed drift between pieces and prevent reset from converging.
        Every item's local shear changes by the same delta so they all
        display the same value. With propagate the selection is its
        items' closure (see _closure).
        """
        history_manager = self._editor.history_manager
        if not items:
            return
        items = self._closure(items, propagate)

        with history_manager.transaction(_("Change item shear")) as t:
            self._shear_group(t, items, shear)

    def _shear_group(self, t, items: list[DocItem], shear: float):
        """set_shear_group's shear, recorded in the transaction *t*."""
        anchor = items[0]
        delta_deg = shear - anchor.shear
        if abs(delta_deg) < 1e-9:
            return

        old_matrices = [item.matrix.copy() for item in items]
        for item in items:
            target_shear = item.shear + delta_deg
            item.shear = target_shear
        self._into_bed(items, old_matrices)
        self._record(t, items, old_matrices)

    def set_size_group(
        self,
        items: list[DocItem],
        width: float | None = None,
        height: float | None = None,
        fixed_ratio: bool = False,
        propagate: bool = True,
    ):
        """Resizes the whole selection uniformly so the combined bounding
        box reaches the given *width* and *height* in world space.

        Each item is scaled around the group's centre by the same
        (scale_x, scale_y) factor, preserving item-to-item offsets.

        When only one dimension is provided and *fixed_ratio* is ``True``,
        the missing dimension is calculated from the group's current aspect
        ratio. With propagate the selection is its items' closure (see
        _closure).
        """
        history_manager = self._editor.history_manager
        if not items:
            return
        items = self._closure(items, propagate)

        bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = self.group_bbox_world(
            items
        )
        cur_w = bbox_max_x - bbox_min_x
        cur_h = bbox_max_y - bbox_min_y

        if cur_w < 1e-9 or cur_h < 1e-9:
            return

        if width is None and height is None:
            return

        final_w: float = cur_w
        final_h: float = cur_h

        if width is not None:
            final_w = width
        if height is not None:
            final_h = height

        if fixed_ratio:
            if width is not None and height is None:
                final_h = final_w * cur_h / cur_w
            elif height is not None and width is None:
                final_w = final_h * cur_w / cur_h

        scale_x = final_w / cur_w
        scale_y = final_h / cur_h

        with history_manager.transaction(_("Resize item(s)")) as t:
            self._scale_group(t, items, scale_x, scale_y)

    def _scale_group(
        self, t, items: list[DocItem], scale_x: float, scale_y: float
    ):
        """Scales the items about their combined box's centre along the
        world axes, recorded in the transaction *t*."""
        center = self.group_center_world(items)

        old_matrices = [item.matrix.copy() for item in items]
        for item in items:
            world_old = item.get_world_transform()

            # Build world-space scale around centre
            scale_matrix = (
                Matrix.identity()
                .post_translate(center[0], center[1])
                .post_scale(scale_x, scale_y)
                .post_translate(-center[0], -center[1])
            )
            world_new = scale_matrix @ world_old
            item.matrix = self._world_to_local_matrix(item, world_new)
        self._into_bed(items, old_matrices)
        self._record(t, items, old_matrices)

    def reset_position(self, items: list[DocItem]):
        """Moves every item's top-left corner to machine (0, 0)."""
        self.set_position(items, 0.0, 0.0)

    def reset_position_group(self, items: list[DocItem]):
        """Moves the selection's bounding box so its origin-corner sits
        at machine (0, 0)."""
        self.set_position_group(items, 0.0, 0.0)

    def reset_angle(self, items: list[DocItem]):
        """Sets every item's angle to 0°."""
        self.set_angle(items, 0.0)

    def reset_angle_group(self, items: list[DocItem], propagate: bool = True):
        """Resets the group's rotation to 0°."""
        self.set_angle_group(items, 0.0, propagate)

    def reset_shear(self, items: list[DocItem]):
        """Sets every item's shear to 0°."""
        self.set_shear(items, 0.0)

    def reset_shear_group(self, items: list[DocItem], propagate: bool = True):
        """Resets the group's shear to 0°."""
        self.set_shear_group(items, 0.0, propagate)

    @classmethod
    def get_position_group(
        cls, items: list[DocItem]
    ) -> tuple[float, float] | None:
        """Machine-coordinate position of the group's bounding-box
        origin-corner (the corner the machine origin refers to).

        Returns ``None`` when the list is empty.
        """
        if not items:
            return None
        machine = get_context().machine
        min_x, min_y, max_x, max_y = cls.group_bbox_world(items)
        gw, gh = max_x - min_x, max_y - min_y
        if machine:
            return machine.panel.world_item_to_machine(
                (min_x, min_y), (gw, gh)
            )
        return (min_x, min_y)

    @classmethod
    def get_size_group(
        cls, items: list[DocItem]
    ) -> tuple[float, float] | None:
        """World-space (width, height) of the group bounding box."""
        if not items:
            return None
        min_x, min_y, max_x, max_y = cls.group_bbox_world(items)
        return (max_x - min_x, max_y - min_y)

    @classmethod
    def get_angle_group(cls, items: list[DocItem]) -> float | None:
        """Angle (degrees) of the anchor item, representing the group."""
        if not items:
            return None
        return items[0].angle

    @classmethod
    def get_shear_group(cls, items: list[DocItem]) -> float | None:
        """Shear (degrees) of the anchor item, representing the group."""
        if not items:
            return None
        return items[0].shear
