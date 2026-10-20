import uuid
from abc import ABC
from gettext import gettext as _
from typing import Any, Self

import numpy as np
from blinker import Signal

from ...core.capability import MachineCapability
from ...core.matrix import TransformMixin

HEAD_TYPE_KEY = "type"

_HEAD_SERIALIZED_KEYS = frozenset(
    {HEAD_TYPE_KEY, "uid", "name", "tool_number", "model_path", "transform"}
)


class Head(TransformMixin, ABC):
    """
    Base class for machine heads.

    Concrete head types (:class:`LaserHead`, :class:`SpindleHead`, ...)
    add their type-specific attributes and declare which machine
    capability they imply via :attr:`machine_capability`.
    """

    # Serialization key identifying the concrete head type.
    HEAD_TYPE: str = "Head"

    def __init__(self):
        self.uid: str = str(uuid.uuid4())
        self.name: str = _("Head")
        self.tool_number: int = 0
        self.model_path: str | None = None
        self.transform: np.ndarray = np.eye(4, dtype=np.float64)
        self.changed = Signal()
        self.extra: dict[str, Any] = {}

    @property
    def machine_capability(self) -> MachineCapability | None:
        """
        The machine capability this head type implies, or ``None`` for
        passive heads that contribute no capability.
        """
        return None

    def set_name(self, name: str):
        self.name = name
        self.changed.send(self)

    def set_tool_number(self, tool_number: int):
        self.tool_number = tool_number
        self.changed.send(self)

    def set_model_path(self, model_path: str | None):
        if self.model_path == model_path:
            return
        self.model_path = model_path
        self.changed.send(self)

    def to_dict(self) -> dict[str, Any]:
        result = {
            HEAD_TYPE_KEY: self.HEAD_TYPE,
            "uid": self.uid,
            "name": self.name,
            "tool_number": self.tool_number,
            "model_path": self.model_path,
            "transform": self.transform.flatten().tolist(),
        }
        result.update(self.extra)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        head = cls()
        head.uid = data.get("uid", str(uuid.uuid4()))
        head.name = data.get("name", head.name)
        head.tool_number = data.get("tool_number", head.tool_number)
        head.model_path = data.get("model_path")
        raw_transform = data.get("transform")
        if raw_transform is not None:
            head.transform = np.array(raw_transform, dtype=np.float64).reshape(
                4, 4
            )
        return head

    def __getstate__(self):
        """Prepare the object for pickling. Removes unpickleable Signal."""
        state = self.__dict__.copy()
        state.pop("changed", None)
        return state

    def __setstate__(self, state):
        """Restore the object after unpickling. Recreates the Signal."""
        vars(self).update(state)
        self.changed = Signal()


def head_from_dict(
    data: dict[str, Any],
) -> "Head":
    """
    Deserialize a head dict, dispatching on the ``type`` key.

    Old machine files without a ``type`` key map to :class:`LaserHead`
    for backward compatibility.
    """
    from .laser import LaserHead
    from .spindle import SpindleHead

    head_type = data.get(HEAD_TYPE_KEY)
    if head_type == SpindleHead.HEAD_TYPE:
        return SpindleHead.from_dict(data)
    return LaserHead.from_dict(data)
