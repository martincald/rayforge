import logging
import math
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from gettext import gettext as _
from typing import TYPE_CHECKING

from raygeo.geo import Geometry

from ..core.item import DocItem
from ..core.undo import ListItemCommand
from ..core.workpiece import WorkPiece

if TYPE_CHECKING:
    from ..core.undo.history import _TransactionContextProxy
    from .editor import DocEditor

logger = logging.getLogger(__name__)

# Open paths whose ends lie this close together (mm) are one shape.
ENDPOINT_TOLERANCE_MM = 1e-3


class SplitStrategy(ABC):
    """
    Abstract base class for strategies that determine how to split a
    WorkPiece's geometry into multiple fragments.
    """

    @abstractmethod
    def calculate_fragments(self, workpiece: "WorkPiece") -> list[Geometry]:
        """
        Calculates the geometric fragments for the split operation.

        Args:
            workpiece: The WorkPiece to split.

        Returns:
            A list of Geometry objects. Each geometry should represent a
            fragment in the same normalized coordinate space (0-1 box, Y-up)
            as the original workpiece's boundaries.
        """


class ConnectivitySplitStrategy(SplitStrategy):
    """
    Splits a workpiece by separating disjoint vector components (islands).
    This is the standard "Split" behavior for vector shapes.
    """

    def calculate_fragments(self, workpiece: "WorkPiece") -> list[Geometry]:
        if not workpiece.boundaries or workpiece.boundaries.is_empty():
            return []
        return workpiece.boundaries.split_into_components()


class PathSplitStrategy(SplitStrategy):
    """
    Splits a workpiece into its paths, in drawing order: one fragment
    per closed path (a hole too), and one per set of open paths joined
    end to end, their ends within ENDPOINT_TOLERANCE_MM. Paths that
    only cross or touch mid-path stay apart. Nothing is dropped, unlike
    ConnectivitySplitStrategy, which keeps holes with their outline and
    drops open paths; its callers keep every fragment too, dust
    included (apply_split's drop_dust=False).
    """

    def calculate_fragments(self, workpiece: "WorkPiece") -> list[Geometry]:
        geo = workpiece.boundaries
        if not geo or geo.is_empty():
            return []
        contours = geo.split_into_contours()
        roots = list(range(len(contours)))

        def find(i: int) -> int:
            while roots[i] != i:
                roots[i] = roots[roots[i]]
                i = roots[i]
            return i

        # The ends of open paths in mm, in a grid of tolerance-sized
        # cells: an end within the tolerance lies in a neighbouring cell.
        width, height = workpiece.size
        tolerance = ENDPOINT_TOLERANCE_MM
        cells: defaultdict[tuple[int, int], list] = defaultdict(list)
        for i, contour in enumerate(contours):
            if contour.is_closed():
                continue
            start = contour.get_command_at(0).end
            for x, y, _z in (start, contour.get_last_point()):
                x, y = x * width, y * height
                cx, cy = math.floor(x / tolerance), math.floor(y / tolerance)
                for nx in (cx - 1, cx, cx + 1):
                    for ny in (cy - 1, cy, cy + 1):
                        for j, ox, oy in cells.get((nx, ny), ()):
                            if math.hypot(ox - x, oy - y) <= tolerance:
                                roots[find(j)] = find(i)
                cells[(cx, cy)].append((i, x, y))

        fragments: dict[int, Geometry] = {}
        for i, contour in enumerate(contours):
            fragments.setdefault(find(i), Geometry()).extend(contour)
        return list(fragments.values())


class SplitCmd:
    """Handles splitting of document items."""

    def __init__(self, editor: "DocEditor"):
        self._editor = editor

    def split_items(
        self,
        items: list[WorkPiece],
        strategy: SplitStrategy | None = None,
    ) -> list[DocItem]:
        """
        Splits the provided items into multiple fragments based on the given
        strategy. Replaces the original items with the new fragments in the
        document.

        Args:
            items: The list of items to split.
            strategy: The strategy to use for calculating fragments.
                      Defaults to splitting disjoint components.

        Returns:
            A list of the newly created items.
        """
        if strategy is None:
            strategy = ConnectivitySplitStrategy()
        if not items:
            return []

        history = self._editor.history_manager
        with history.transaction(_("Split item(s)")) as t:
            return self.split_in_transaction(t, items, strategy)

    def split_in_transaction(
        self,
        t: "_TransactionContextProxy",
        items: list[WorkPiece],
        strategy: SplitStrategy,
        drop_dust: bool = True,
    ) -> list[DocItem]:
        """
        Splits the items like split_items, executing the commands in the
        caller's open transaction t, so a split can be part of a larger
        undo step. Without drop_dust, fragments under 0.1 mm are kept.

        Returns:
            A list of the newly created items.
        """
        newly_created_items: list[DocItem] = []
        for item in items:
            # Capture the parent before any modification/removal occurs.
            # Executing remove_cmd may set item.parent to None.
            parent = item.parent
            if not isinstance(item, WorkPiece) or not parent:
                continue

            fragments = strategy.calculate_fragments(item)
            new_pieces = item.apply_split(fragments, drop_dust=drop_dust)

            # If splitting didn't produce multiple pieces, do nothing for
            # this item.
            if len(new_pieces) <= 1:
                continue

            # Remove the original
            remove_cmd = ListItemCommand(
                owner_obj=parent,
                item=item,
                undo_command="add_child",
                redo_command="remove_child",
                name=_("Remove original item"),
            )
            t.execute(remove_cmd)

            # Add the new pieces
            for piece in new_pieces:
                # Assign a unique ID to each new piece
                piece.uid = str(uuid.uuid4())

            add_cmd = ListItemCommand(
                owner_obj=parent,
                item=new_pieces,
                undo_command="remove_children",
                redo_command="add_children",
                name=_("Add split fragments"),
            )
            t.execute(add_cmd)
            newly_created_items.extend(new_pieces)

        return newly_created_items
