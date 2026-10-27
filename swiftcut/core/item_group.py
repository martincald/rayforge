"""
Groups that tie items on any layers together, so they move as one
object while each stays on its own layer: a cut outline and its
engrave artwork, say. A group is a relation the document keeps beside
its tree, by uid. The job is built per layer and step from the tree,
so it never sees a group.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Union

from blinker import Signal

from .undo import Command

if TYPE_CHECKING:
    from .doc import Doc
    from .item import DocItem

# What a selection is made of: an item in no group, or the outermost
# group of one that is in a group.
Unit = Union["DocItem", "ItemGroup"]


class ItemGroup:
    """
    A group: its members, items on any layers or other groups, by uid
    and in order. An item is in at most one group.
    """

    def __init__(self, member_uids: Iterable[str] = (), name: str = "Group"):
        self.uid: str = str(uuid.uuid4())
        self.name: str = name
        self.member_uids: list[str] = list(member_uids)

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "name": self.name,
            "members": list(self.member_uids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ItemGroup:
        group = cls(data.get("members", []), data.get("name", "Group"))
        group.uid = data["uid"]
        return group


class ItemGroups:
    """
    A document's groups, in order. A member item is looked up by its uid
    among the layers' content items, so one moved to another layer
    stays in its group, and one deleted drops out of it until an undo
    brings it back. `changed` is sent after every change.
    """

    def __init__(self, doc: Doc):
        self._doc = doc
        self._groups: list[ItemGroup] = []
        # The group each member uid is in.
        self._parents: dict[str, ItemGroup] = {}
        self.changed = Signal()

    def __iter__(self) -> Iterator[ItemGroup]:
        return iter(list(self._groups))

    def __len__(self) -> int:
        return len(self._groups)

    def get(self, uid: str) -> ItemGroup | None:
        return next((g for g in self._groups if g.uid == uid), None)

    def index(self, group: ItemGroup) -> int:
        return self._groups.index(group)

    def add(self, group: ItemGroup, index: int | None = None) -> None:
        """
        Adds a group. Raises ValueError if one of its members is in a
        group already, or if the group holds itself.
        """
        taken = [uid for uid in group.member_uids if uid in self._parents]
        if taken or group.uid in group.member_uids:
            raise ValueError(f"Already in a group: {taken or [group.uid]}")
        if index is None:
            self._groups.append(group)
        else:
            self._groups.insert(index, group)
        self._reindex()

    def remove(self, group: ItemGroup) -> None:
        """Removes a group; its members are in no group afterwards."""
        self._groups.remove(group)
        self._reindex()

    def update(
        self,
        group: ItemGroup,
        name: str | None = None,
        member_uids: Iterable[str] | None = None,
    ) -> None:
        """Renames a group or sets its members."""
        if name is not None:
            group.name = name
        if member_uids is not None:
            group.member_uids = list(member_uids)
        self._reindex()

    def load(self, data: Iterable[dict]) -> None:
        """Replaces all groups with those of a saved document."""
        self._groups = [ItemGroup.from_dict(d) for d in data]
        self._reindex()

    def _reindex(self) -> None:
        self._parents = {
            uid: group for group in self._groups for uid in group.member_uids
        }
        self.changed.send(self)

    def parent_of(self, uid: str) -> ItemGroup | None:
        """The group that holds uid (an item's or a group's), if any."""
        return self._parents.get(uid)

    def top_of(self, uid: str) -> ItemGroup | None:
        """The outermost group that holds uid, if any."""
        top = None
        parent = self._parents.get(uid)
        while parent is not None:
            top = parent
            parent = self._parents.get(parent.uid)
        return top

    def _content(self) -> dict[str, DocItem]:
        """The layers' content items by uid: what a member can be."""
        return {
            item.uid: item
            for layer in self._doc.layers
            for item in layer.get_content_items()
        }

    def members(self, group: ItemGroup) -> list[DocItem | ItemGroup]:
        """A group's members that exist, items and groups, in order."""
        content = self._content()
        found: list[DocItem | ItemGroup] = []
        for uid in group.member_uids:
            item = content.get(uid)
            member = item if item is not None else self.get(uid)
            if member is not None:
                found.append(member)
        return found

    def items_of(
        self,
        group: ItemGroup,
        content: dict[str, DocItem] | None = None,
    ) -> list[DocItem]:
        """
        Every item in a group, in its nested groups too, in order;
        members that do not exist (deleted) left out.
        """
        content = self._content() if content is None else content
        found: list[DocItem] = []
        for uid in group.member_uids:
            item = content.get(uid)
            if item is not None:
                found.append(item)
                continue
            nested = self.get(uid)
            if nested is not None:
                found.extend(self.items_of(nested, content))
        return found

    def unit_of(self, item: DocItem) -> Unit:
        """The outermost group an item is in, or the item itself."""
        top = self.top_of(item.uid)
        return item if top is None else top

    def units(self, items: Iterable[DocItem]) -> list[Unit]:
        """The items as units (see unit_of), each once, in order."""
        found: dict[int, Unit] = {}
        for item in items:
            unit = self.unit_of(item)
            found.setdefault(id(unit), unit)
        return list(found.values())

    def closure(self, items: Iterable[DocItem]) -> list[DocItem]:
        """
        The items, then every other item of their outermost groups,
        each once: what moves when the items move.
        """
        content = self._content()
        found: dict[str, DocItem] = {}
        tops: list[ItemGroup] = []
        for item in items:
            found.setdefault(item.uid, item)
            top = self.top_of(item.uid)
            if top is not None and top not in tops:
                tops.append(top)
        for top in tops:
            for member in self.items_of(top, content):
                found.setdefault(member.uid, member)
        return list(found.values())

    def to_list(self) -> list[dict]:
        """
        The groups as saved: a group with no item left is not, nor are
        the uids of members that do not exist.
        """
        content = self._content()
        kept = [g for g in self._groups if self.items_of(g, content)]
        kept_uids = {g.uid for g in kept}
        saved = []
        for group in kept:
            data = group.to_dict()
            data["members"] = [
                uid
                for uid in group.member_uids
                if uid in content or uid in kept_uids
            ]
            saved.append(data)
        return saved


class AddItemGroupCommand(Command):
    """Adds a group to a document's groups; undo removes it."""

    def __init__(
        self,
        groups: ItemGroups,
        group: ItemGroup,
        index: int | None = None,
        name: str | None = None,
    ):
        super().__init__(name)
        self.groups = groups
        self.group = group
        self.index = index

    def execute(self) -> None:
        self.groups.add(self.group, self.index)

    def undo(self) -> None:
        self.groups.remove(self.group)


class RemoveItemGroupCommand(Command):
    """Removes a group; undo puts it back where it was."""

    def __init__(
        self, groups: ItemGroups, group: ItemGroup, name: str | None = None
    ):
        super().__init__(name)
        self.groups = groups
        self.group = group
        self._index = 0

    def execute(self) -> None:
        self._index = self.groups.index(self.group)
        self.groups.remove(self.group)

    def undo(self) -> None:
        self.groups.add(self.group, self._index)


class UpdateItemGroupCommand(Command):
    """Renames a group or sets its members; undo restores both."""

    def __init__(
        self,
        groups: ItemGroups,
        group: ItemGroup,
        new_name: str | None = None,
        member_uids: Iterable[str] | None = None,
        name: str | None = None,
    ):
        super().__init__(name)
        self.groups = groups
        self.group = group
        self.new_name = new_name
        self.member_uids = None if member_uids is None else list(member_uids)
        self._old = (group.name, list(group.member_uids))

    def execute(self) -> None:
        self.groups.update(self.group, self.new_name, self.member_uids)

    def undo(self) -> None:
        self.groups.update(self.group, *self._old)
