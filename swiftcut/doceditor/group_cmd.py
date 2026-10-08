import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from gettext import gettext as _
from typing import TYPE_CHECKING

from raygeo.geo import Matrix

from ..core.group import Group, GroupingResult
from ..core.item import DocItem
from ..core.layer import Layer
from ..core.undo.command import Command
from ..core.workpiece import WorkPiece
from .split_cmd import PathSplitStrategy

if TYPE_CHECKING:
    from ..pipeline.pipeline import Pipeline
    from ..shared.tasker.context import ExecutionContext
    from ..shared.tasker.manager import TaskManager
    from ..shared.tasker.task import Task
    from .editor import DocEditor

logger = logging.getLogger(__name__)


class _CreateGroupCommand(Command):
    """An undoable command to group a list of DocItems into a new Group."""

    def __init__(
        self,
        layer: Layer,
        items_to_group: list[DocItem],
        pipeline: "Pipeline",
        name: str = "Group Items",
        precalculated_result: GroupingResult | None = None,
    ):
        super().__init__(name)
        self.layer = layer
        self.items_to_group = list(items_to_group)
        self.pipeline = pipeline
        self.new_group: Group | None = None
        self._original_parents: dict[str, DocItem] = {
            item.uid: item.parent
            for item in self.items_to_group
            if item.parent
        }
        self._original_matrices: dict[str, Matrix] = {
            item.uid: item.matrix.copy() for item in self.items_to_group
        }
        self._precalculated_result = precalculated_result

    def execute(self) -> None:
        """Performs the grouping operation."""
        # The result must be pre-calculated by the background task.
        if not self._precalculated_result:
            return

        result = self._precalculated_result

        # Pause the generator to prevent it from reacting to the storm of
        # add/remove signals during the model mutation.
        with self.pipeline.paused():
            self.new_group = result.new_group
            self.layer.add_child(self.new_group)

            # --- Bulk Reparenting to Prevent Signal Storm ---
            # 1. Group items by their original parent.
            items_by_parent = defaultdict(list)
            for item in self.items_to_group:
                if item.parent:
                    items_by_parent[item.parent].append(item)

            # 2. Remove items from old parents in batches.
            for parent, items in items_by_parent.items():
                parent.remove_children(items)

            # 3. Add all items to the new group in one batch.
            self.new_group.add_children(self.items_to_group)

            # 4. Set final local matrices *after* reparenting is complete.
            for item in self.items_to_group:
                item.matrix = result.child_matrices[item.uid]

    def undo(self) -> None:
        """Reverts the grouping operation."""
        if not self.new_group:
            return

        with self.pipeline.paused():
            # --- Bulk Reparenting for Undo ---
            # 1. Remove all children from the group in one batch.
            self.new_group.remove_children(self.items_to_group)

            # 2. Group items by their original parent for re-adding.
            items_by_original_parent = defaultdict(list)
            for item in self.items_to_group:
                original_parent = self._original_parents.get(item.uid)
                if original_parent:
                    items_by_original_parent[original_parent].append(item)

            # 3. Re-add items to their original parents in batches and
            # restore their original matrices.
            for parent, items in items_by_original_parent.items():
                parent.add_children(items)
            for item in self.items_to_group:
                item.matrix = self._original_matrices[item.uid]

            # 5. Finally, remove the now-empty group.
            self.layer.remove_child(self.new_group)


class _UngroupCommand(Command):
    """An undoable command to dissolve one or more Groups."""

    def __init__(
        self,
        groups_to_ungroup: list[Group],
        pipeline: "Pipeline",
        name: str = "Ungroup Items",
        precalculated_matrices: dict[str, dict[str, Matrix]] | None = None,
    ):
        super().__init__(name)
        self.groups_to_ungroup = list(groups_to_ungroup)
        self.pipeline = pipeline
        self._precalculated_matrices = precalculated_matrices
        self._undo_data = []
        for group in self.groups_to_ungroup:
            if group.parent:
                self._undo_data.append(
                    {
                        "group_uid": group.uid,
                        "group_matrix": group.matrix.copy(),
                        "parent": group.parent,
                        "group_index": group.parent.children.index(group),
                        "children": list(group.children),
                        "child_matrices": {
                            c.uid: c.matrix.copy() for c in group.children
                        },
                    }
                )

    @staticmethod
    def _calculate_ungroup_transforms(
        group: Group, parent_inv_world: Matrix
    ) -> dict[str, Matrix]:
        """
        Calculates the new local matrices for a group's children using a
        pre-calculated parent inverse transform.
        """
        group_world_transform = group.get_world_transform()
        new_child_matrices = {}
        for child in group.children:
            child_world_transform = group_world_transform @ child.matrix
            new_child_matrices[child.uid] = (
                parent_inv_world @ child_world_transform
            )
        return new_child_matrices

    def execute(self) -> None:
        """Performs the ungrouping operation."""
        with self.pipeline.paused():
            for group in self.groups_to_ungroup:
                parent = group.parent
                if not parent:
                    continue

                try:
                    group_index = parent.children.index(group)
                except ValueError:
                    continue  # Should not happen

                children_to_move = list(group.children)

                if self._precalculated_matrices:
                    if group.uid not in self._precalculated_matrices:
                        continue
                    new_child_matrices = self._precalculated_matrices[
                        group.uid
                    ]
                else:
                    # Ungroup computes the matrices from the tree as it is.
                    parent_inv = parent.get_world_transform().invert()
                    new_child_matrices = (
                        _UngroupCommand._calculate_ungroup_transforms(
                            group, parent_inv
                        )
                    )

                # Set new matrices before reparenting
                for child in children_to_move:
                    child.matrix = new_child_matrices[child.uid]

                parent.remove_child(group)
                parent.add_children(children_to_move, index=group_index)

    def undo(self) -> None:
        """Reverts the ungrouping by re-creating the original groups."""
        with self.pipeline.paused():
            for data in reversed(self._undo_data):
                parent = data["parent"]
                group_index = data["group_index"]
                children = data["children"]
                group = next(
                    (
                        g
                        for g in self.groups_to_ungroup
                        if g.uid == data["group_uid"]
                    ),
                    None,
                )
                if not group:
                    continue

                # Restore matrices first
                group.matrix = data["group_matrix"]
                for child in children:
                    child.matrix = data["child_matrices"][child.uid]

                # Move children from parent back into the group
                parent.remove_children(children)
                group.set_children(children)  # Fast, as group starts empty

                # Add group back to its parent and restore its matrix
                parent.add_child(group, index=group_index)


class GroupCmd:
    """Handles grouping and ungrouping of document items."""

    def __init__(self, editor: "DocEditor", task_manager: "TaskManager"):
        self._editor = editor
        self._task_manager = task_manager

    def group_items(
        self,
        layer: Layer,
        items_to_group: list[DocItem],
        on_done: Callable[[Group], None] | None = None,
    ):
        """
        Creates and executes an undoable command to group items. This operation
        runs as a background task; on_done then receives the new group.
        """
        if not items_to_group:
            return

        # Notify editor that we are starting a background task
        self._editor.notify_task_started()

        async def group_coro(context: "ExecutionContext"):
            context.set_message(_("Grouping items..."))
            context.flush()
            await asyncio.sleep(0.01)

            result = Group.create_from_items(items_to_group, layer)

            context.set_progress(1.0)
            return result

        def when_done(task: "Task"):
            try:
                if task.get_status() != "completed":
                    logger.error(
                        "Group task did not complete successfully. Status: %s",
                        task.get_status(),
                    )
                    return

                result: GroupingResult | None = task.result()
                if not result:
                    return

                command = _CreateGroupCommand(
                    layer=layer,
                    items_to_group=items_to_group,
                    pipeline=self._editor.pipeline,
                    precalculated_result=result,
                )
                self._editor.history_manager.execute(command)
                if on_done and command.new_group:
                    on_done(command.new_group)
            finally:
                # Always notify editor when done, even on failure
                self._editor.notify_task_ended()

        self._task_manager.add_coroutine(
            group_coro,
            when_done=when_done,
            key="group-items",
        )

    def ungroup_items(self, items: list[DocItem]) -> list[DocItem]:
        """
        Ungroups the items in one undoable step: each Group is dissolved
        one level, its children going back to its parent (the inverse of
        Group), and each WorkPiece of several paths is split into one
        piece per path (see PathSplitStrategy). Nothing else is touched.

        Returns:
            The freed children and the new pieces. Empty, with no history
            entry, when there is nothing to ungroup.
        """
        groups = [i for i in items if isinstance(i, Group) and i.parent]
        workpieces = [i for i in items if isinstance(i, WorkPiece)]
        children = [child for group in groups for child in group.children]

        with self._editor.history_manager.transaction(_("Ungroup")) as t:
            if groups:
                t.execute(_UngroupCommand(groups, self._editor.pipeline))
            pieces = self._editor.split.split_in_transaction(
                t, workpieces, PathSplitStrategy(), drop_dust=False
            )
        return children + pieces
