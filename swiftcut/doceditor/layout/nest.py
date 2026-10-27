"""
Auto Layout on true outlines: the items gather in a tight pile centred
on the stock or the bed, the Auto Layout gap (Preferences) clear of
each other and of every other workpiece. At gap 0 they touch, with
straight edges laid flush so a shared edge is cut once.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from gettext import gettext as _
from typing import TYPE_CHECKING, Any

from raygeo.geo import Matrix

from ...context import get_context
from ...core.bed_bounds import bed_rect
from ...core.item import DocItem
from ...core.layer import Layer
from ...core.workpiece import WorkPiece
from ...shared.placement import Piece, arrange
from ...shared.tasker.context import ExecutionContext
from .base import LayoutStrategy
from .outline import (
    OUTLINE_TOLERANCE_MM,
    item_world_polygons,
    item_world_polygons_and_edges,
)

if TYPE_CHECKING:
    from ...core.doc import Doc
    from ...core.step import Step

logger = logging.getLogger(__name__)

# The name of the Merge Lines settings among a step's per-step
# transformer settings: the transformer that cuts shared edges once.
_MERGE_LINES = "MergeLinesTransformer"


class NestLayoutStrategy(LayoutStrategy):
    """
    Arranges items in a tight pile centred on the boundary (the part of
    the visible stock's bounding box on the bed, else the bed), largest
    first, each where and by the quarter turn that grows the pile's box
    least (see shared.placement.arrange); mirroring is kept. Their
    outlines keep the Auto Layout gap from each other and from every
    other workpiece in the document, and their frames stay inside the
    boundary. Items that fit nowhere stay where they are, with a
    notice. An item and its followers are laid out as one piece,
    framed by their combined box.

    At gap 0 the outlines may touch, and straight edges are laid flush
    within the Merge Lines tolerance of the items' and followers'
    layers' steps (see _merge_lines), so Merge Lines cuts a shared
    edge once; merge_lines_off lists the (step, settings) of each
    Merge Lines that is off. Curves are polygonized as at any gap:
    raygeo's polygons at OUTLINE_TOLERANCE_MM lie within about
    0.001 mm of arcs and Beziers, so touching curves overlap far less
    than the Merge Lines tolerance (see test_layout_outline), though a
    small arc scaled very unevenly can lie up to about 0.02 mm off.
    With no Merge Lines on those layers nothing is laid flush, and the
    outlines keep twice OUTLINE_TOLERANCE_MM, so true curves touch at
    most.

    The document is read when the strategy is built, which must be on
    the main thread; arrange_args hands that to arrange, which may run
    anywhere, and deltas turns its result into the items' deltas.
    changed tells whether the document has moved on meanwhile.
    """

    def __init__(self, items: Sequence[DocItem], **kwargs):
        super().__init__(items, **kwargs)
        doc = self.items[0].doc
        assert doc is not None, "Auto Layout needs items in a document."
        order = {item: n for n, item in enumerate(doc.get_descendants())}
        self.items.sort(key=lambda item: order[item])

        gap = get_context().config.layout_gap_mm
        # Both outlines may lie up to the tolerance inside the curves.
        self._clearance = gap + 2 * OUTLINE_TOLERANCE_MM
        self._flush_tolerance: float | None = None
        self.merge_lines_off: list[tuple[Step, dict[str, Any]]] = []
        if gap <= 0:
            members = [
                member
                for item in self.items
                for member in (item, *self.followers.get(item, ()))
            ]
            self._flush_tolerance, self.merge_lines_off = _merge_lines(members)
        if self._flush_tolerance is not None:
            self._clearance = 0.0

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

        # Pieces name their item by its index in self.items. An item
        # and its followers are one piece, moved by the item's delta.
        self._pieces: list[Piece] = []
        self._parents: dict[DocItem, Matrix] = {}
        moving: set[DocItem] = set()
        for n, item in enumerate(self.items):
            unit = (item, *self.followers.get(item, ()))
            outlines, edges = [], []
            for member in unit:
                polygons, straight = self._outlines(member)
                outlines.extend(polygons)
                edges.extend(straight)
            box = self._unit_bbox(item)
            if not outlines or not box:
                continue
            x0, y0, x1, y1 = box
            frame = (x0, y0, x1 - x0, y1 - y0)
            self._pieces.append(Piece(n, outlines, frame, tuple(edges)))
            self._parents[item] = (
                item.parent.get_world_transform()
                if item.parent
                else Matrix.identity()
            )
            for member in unit:
                moving.add(member)
                moving.update(member.get_descendants(of_type=WorkPiece))
        self._obstacles: list = []
        self._obstacle_edges: list = []
        for workpiece in doc.all_workpieces:
            if workpiece not in moving:
                polygons, edges = self._outlines(workpiece)
                self._obstacles.extend(polygons)
                self._obstacle_edges.extend(edges)
        # What the layout is worked out on (see changed).
        self.doc = doc
        self._read = self._positions()

    def _outlines(self, item: DocItem) -> tuple:
        """
        The item's outer outlines, and when edges are laid flush their
        straight edges (none otherwise).
        """
        if self._flush_tolerance is None:
            return item_world_polygons(item), ()
        return item_world_polygons_and_edges(item)

    def changed(self) -> bool:
        """
        Whether, since the strategy read the document, an item or a
        follower left it, or an item, follower, workpiece or stock in
        it moved, came or went.
        """
        return self._positions() != self._read

    def _positions(self) -> list[tuple[DocItem, Doc | None, Matrix]]:
        """
        The items, followers, workpieces and stocks, each with its
        document and world transform.
        """
        return [
            (item, item.doc, item.get_world_transform())
            for item in (
                *self.items,
                *(f for moved in self.followers.values() for f in moved),
                *self.doc.all_workpieces,
                *self.doc.stock_items,
            )
        ]

    def calculate_deltas(
        self, context: ExecutionContext | None = None
    ) -> dict[DocItem, Matrix]:
        """Runs arrange here and gives its deltas (see deltas)."""
        args = self.arrange_args()
        if args is None:
            return {}
        return self.deltas(arrange(context or ExecutionContext(), *args))

    def arrange_args(self) -> tuple | None:
        """
        What shared.placement.arrange takes after its progress context
        (plain data, so a worker process can run it), with the
        obstacles' edges and the flush tolerance when edges are laid
        flush; None when there is neither a stock nor a machine bed.
        """
        if self._boundary is None:
            logger.warning("Auto Layout: no stock and no machine bed.")
            return None
        bx, by, bw, bh = self._boundary
        args = (
            self._pieces,
            self._obstacles,
            self._boundary,
            (bx + bw / 2, by + bh / 2),
            self._clearance,
        )
        if self._flush_tolerance is None:
            return args
        return (*args, self._obstacle_edges, self._flush_tolerance)

    def deltas(
        self, placements: dict[int, tuple[float, float, float, bool]]
    ) -> dict[DocItem, Matrix]:
        """
        From arrange's result, the delta for each item that fits: a
        turn about its frame's centre and a move, in world space,
        expressed in its parent's space (layout_cmd applies it as
        `delta @ item.matrix`, and moves the item's followers by it).
        Items that do not fit get a notice.
        """
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


def _merge_lines(
    items: Sequence[DocItem],
) -> tuple[float | None, list[tuple[Step, dict[str, Any]]]]:
    """
    The tolerance Merge Lines merges shared edges within, over the
    Merge Lines settings of every step on the items' layers: the least
    "tolerance" of those that are on, or if none is, of those that are
    off (what Enable would merge at); None where there are none. One
    without a "tolerance" gives none, but counts as on or off. And the
    (step, settings) of each that is off.
    """
    layers = dict.fromkeys(item.get_ancestor_by_type(Layer) for item in items)
    on, off = [], []
    for layer in layers:
        workflow = layer.workflow if isinstance(layer, Layer) else None
        for step in workflow.steps if workflow else ():
            for settings in step.per_step_transformers_dicts:
                if settings.get("name") == _MERGE_LINES:
                    enabled = settings.get("enabled", True)
                    (on if enabled else off).append((step, settings))
    tolerances = [s["tolerance"] for _step, s in on or off if "tolerance" in s]
    return (min(tolerances) if tolerances else None), off
