"""TransformMixin: rotation and uniform scale of a placed 3D part."""

import numpy as np
import pytest
from blinker import Signal

from swiftcut.core.matrix import TransformMixin


class Part(TransformMixin):
    def __init__(self):
        self.transform = np.eye(4, dtype=np.float64)
        self.transform[:3, 3] = (10.0, 20.0, 30.0)
        self.changed = Signal()
        self.sent = 0
        self.changed.connect(self._count, weak=False)

    def _count(self, sender):
        self.sent += 1


def test_rotation_round_trips():
    part = Part()

    part.set_rotation(10.0, -20.0, 30.0)

    assert part.get_rotation() == pytest.approx((10.0, -20.0, 30.0))
    assert part.sent == 1


def test_scale_keeps_rotation_and_position():
    part = Part()
    part.set_rotation(0.0, 0.0, 45.0)

    part.set_scale(2.5)

    assert part.get_scale() == pytest.approx(2.5)
    assert part.get_rotation() == pytest.approx((0.0, 0.0, 45.0))
    assert tuple(part.transform[:3, 3]) == (10.0, 20.0, 30.0)


def test_setting_the_same_values_sends_nothing():
    part = Part()

    part.set_rotation(0.0, 0.0, 0.0)
    part.set_scale(1.0)

    assert part.sent == 0


def test_head_and_rotary_module_share_it():
    from swiftcut.machine.models.head import Head
    from swiftcut.machine.models.rotary_module import RotaryModule

    assert issubclass(Head, TransformMixin)
    assert issubclass(RotaryModule, TransformMixin)
