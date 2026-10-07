"""
Auto Layout on true outlines: the items gather around the centre of
the stock or the bed, 1 mm clear of each other and of every other
workpiece.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from gettext import gettext as _

from raygeo.geo import Matrix

from ...context import get_context
from ...core.bed_bounds import bed_rect
from ...core.item import DocItem
from ...core.workpiece import WorkPiece
from ...shared.placement import Piece, arrange
from ...shared.tasker.context import ExecutionContext
from .base import LayoutStrategy
from .outline import OUTLINE_TOLERANCE_MM, item_world_polygons

logger = logging.getLogger(__name__)


class NestLayoutStrategy(LayoutStrategy):
    """
    Arranges items as close to the centre of the boundary (the part of
    the visible stock's bounding box on the bed, else the bed) as they
    go, largest first, each turned by the quarter turn that lands it
    nearest; mirroring is kept. Their outlines keep 1 mm from each
    other and from every other workpiece in the document, and their
    frames stay inside the boundary. Items that fit nowhere stay where
    they are, with a notice.

    The document is read when the strategy is built, which must be on
    the main thread; calculate_deltas only computes from that.
    """

    def __init__(self, items: Sequence[DocItem], **kwargs):
        super().__init__(items, **kwargs)
        doc = self.items[0].doc
        assert doc is not None, "Auto Layout needs items in a document."
        order = {item: n for n, item in enumerate(doc.get_descendants())}
        self.items.sort(key=lambda item: order[item])

        stocks = [s for s in doc.stock_items if s.visible]
        stock_box = self._get_item_world_bbox(stocks[0]) if stocks else None
        machine = get_context().machine
        self._boundary = None
        if machine:
            bx, by, bw, bh = bed_rect(machine)
            self._boundary = (bx, by, bw, bh)
            if stock_box:
                # Frames stay on the bed too: only the stock's part on
                # it counts (none left gives a boundary of size 0).
                x0, y0 = max(stock_box[0], bx), max(stock_box[1], by)
                x1 = max(min(stock_box[2], bx + bw), x0)
                y1 = max(min(stock_box[3], by + bh), y0)
                self._boundary = (x0, y0, x1 - x0, y1 - y0)
        elif stock_box:
            x0, y0, x1, y1 = stock_box
            self._boundary = (x0, y0, x1 - x0, y1 - y0)

        # Pieces name their item by its index in self.items.
        self._pieces: list[Piece] = []
        self._parents: dict[DocItem, Matrix] = {}
        moving: set[DocItem] = set()
        for n, item in enumerate(self.items):
            outlines = item_world_polygons(item)
            box = self._get_item_world_bbox(item)
            if not outlines or not box:
                continue
            x0, y0, x1, y1 = box
            frame = (x0, y0, x1 - x0, y1 - y0)
            self._pieces.append(Piece(n, outlines, frame))
            self._parents[item] = (
                item.parent.get_world_transform()
                if item.parent
                else Matrix.identity()
            )
            moving.add(item)
            moving.update(item.get_descendants(of_type=WorkPiece))
        self._obstacles = [
            polygon
            for workpiece in doc.all_workpieces
            if workpiece not in moving
            for polygon in item_world_polygons(workpiece)
        ]

    def calculate_deltas(
        self, context: ExecutionContext | None = None
    ) -> dict[DocItem, Matrix]:
        """
        The delta for each item that fits: a turn about its frame's
        centre and a move, in world space, expressed in its parent's
        space (layout_cmd applies it as `delta @ item.matrix`).
        """
        if self._boundary is None:
            logger.warning("Auto Layout: no stock and no machine bed.")
            return {}
        bx, by, bw, bh = self._boundary
        placements = arrange(
            context or ExecutionContext(),
            self._pieces,
            self._obstacles,
            self._boundary,
            (bx + bw / 2, by + bh / 2),
            # Both outlines may lie up to the tolerance inside the curves.
            clearance=1.0 + 2 * OUTLINE_TOLERANCE_MM,
        )
        if not placements:
            return {}

        deltas: dict[DocItem, Matrix] = {}
        unplaced = []
        for piece in self._pieces:
            item = self.items[piece.id]
            angle, dx, dy, fits = placements[piece.id]
            if not fits:
                unplaced.append(item)
                continue
            x, y, w, h = piece.frame
            world = Matrix.translation(dx, dy) @ Matrix.rotation(
                angle, center=(x + w / 2, y + h / 2)
            )
            parent = self._parents[item]
            deltas[item] = parent.invert() @ world @ parent

        logger.info(
            f"Auto Layout placed {len(deltas)} of {len(self._pieces)} item(s)."
        )
        if unplaced:
            item_names = ", ".join(item.name for item in unplaced)
            self.error_reported.send(
                self,
                message=_(
                    "Could not fit the following items: {item_names}"
                ).format(item_names=item_names),
            )
        return deltas
