"""The start corner: where the head is when the job starts.

The selected corner of the job's bounding box lands on the head and
the job grows toward the opposite corner. MachinePanel.
start_corner_offset is the one helper that says how far the head moves
first, and it takes its directions from calculate_jog -- the arrow
keys' mapping -- so the checks below judge it against calculate_jog
directly, on every axis convention a profile can have.
"""

from unittest.mock import patch

import pytest
from raygeo.ops.axis import Axis

from swiftcut.machine.models.machine import (
    JogDirection,
    Machine,
    Origin,
    StartCorner,
)
from swiftcut.machine.models.machine_panel import (
    MachinePanel,
    PanelOrientation,
)

WIDTH = 50.0
HEIGHT = 30.0
HEAD = (200.0, 150.0)

OPPOSITE = {
    StartCorner.TOP_LEFT: StartCorner.BOTTOM_RIGHT,
    StartCorner.TOP_RIGHT: StartCorner.BOTTOM_LEFT,
    StartCorner.BOTTOM_LEFT: StartCorner.TOP_RIGHT,
    StartCorner.BOTTOM_RIGHT: StartCorner.TOP_LEFT,
}

CONVENTIONS = [
    (origin, reverse_x, reverse_y, orientation)
    for origin in Origin
    for reverse_x in (False, True)
    for reverse_y in (False, True)
    for orientation in PanelOrientation
]


def _along(vector: dict[Axis, float], point: tuple[float, float]) -> float:
    """How far a native point lies along a native jog vector."""
    return point[0] * vector.get(Axis.X, 0.0) + point[1] * vector.get(
        Axis.Y, 0.0
    )


def visual_corner(
    panel: MachinePanel,
    rect: tuple[float, float, float, float],
    corner: StartCorner,
) -> tuple[float, float]:
    """The native point of a rectangle that the arrows call ``corner``.

    Left is the least far east, top the least far south, both as the
    arrow keys move -- the oracle is calculate_jog itself.
    """
    x0, y0, x1, y1 = rect
    east = panel.calculate_jog(JogDirection.EAST, 1.0)
    south = panel.calculate_jog(JogDirection.SOUTH, 1.0)
    left = corner in (StartCorner.TOP_LEFT, StartCorner.BOTTOM_LEFT)
    top = corner in (StartCorner.TOP_LEFT, StartCorner.TOP_RIGHT)
    return min(
        ((x, y) for x in (x0, x1) for y in (y0, y1)),
        key=lambda p: (
            (1 if left else -1) * _along(east, p)
            + (1 if top else -1) * _along(south, p)
        ),
    )


def job_rect(panel: MachinePanel, corner: StartCorner):
    """The native rectangle a job occupies once it is anchored."""
    dx, dy = panel.start_corner_offset(corner, WIDTH, HEIGHT)
    x0, y0 = HEAD[0] + dx, HEAD[1] + dy
    return x0, y0, x0 + WIDTH, y0 + HEIGHT


@pytest.fixture
def machine(lite_context):
    machine = Machine(lite_context)
    machine.set_axis_extents(800.0, 600.0)
    return machine


def _configure(machine, origin, reverse_x, reverse_y, orientation):
    machine.set_origin(origin)
    machine.set_reverse_x_axis(reverse_x)
    machine.set_reverse_y_axis(reverse_y)
    machine.panel.set_orientation(orientation)


@pytest.mark.parametrize("corner", list(StartCorner))
@pytest.mark.parametrize(
    "origin, reverse_x, reverse_y, orientation", CONVENTIONS
)
def test_the_head_is_on_the_selected_corner(
    machine, corner, origin, reverse_x, reverse_y, orientation
):
    _configure(machine, origin, reverse_x, reverse_y, orientation)
    panel = machine.panel

    rect = job_rect(panel, corner)

    assert visual_corner(panel, rect, corner) == pytest.approx(HEAD)


@pytest.mark.parametrize("corner", list(StartCorner))
@pytest.mark.parametrize(
    "origin, reverse_x, reverse_y, orientation", CONVENTIONS
)
def test_the_job_grows_toward_the_opposite_corner(
    machine, corner, origin, reverse_x, reverse_y, orientation
):
    """Walking from the head the way the arrows point reaches it."""
    _configure(machine, origin, reverse_x, reverse_y, orientation)
    panel = machine.panel
    rect = job_rect(panel, corner)
    extents = {Axis.X: WIDTH, Axis.Y: HEIGHT}

    far = list(HEAD)
    for direction in corner.toward_opposite:
        for axis, delta in panel.calculate_jog(direction, 1.0).items():
            index = 0 if axis is Axis.X else 1
            far[index] += delta * extents[axis]

    assert tuple(far) == pytest.approx(
        visual_corner(panel, rect, OPPOSITE[corner])
    )


def test_top_left_grows_down_and_to_the_right(machine):
    """The case the operator reads off the button, spelled out."""
    panel = machine.panel
    rect = job_rect(panel, StartCorner.TOP_LEFT)

    right = panel.calculate_jog(JogDirection.EAST, 1.0)
    down = panel.calculate_jog(JogDirection.SOUTH, 1.0)
    others = [
        p
        for p in ((x, y) for x in rect[0::2] for y in rect[1::2])
        if p != pytest.approx(HEAD)
    ]
    assert all(_along(right, p) >= _along(right, HEAD) for p in others)
    assert all(_along(down, p) >= _along(down, HEAD) for p in others)


@pytest.mark.parametrize(
    "corner, directions",
    [
        (StartCorner.TOP_LEFT, (JogDirection.EAST, JogDirection.SOUTH)),
        (StartCorner.TOP_RIGHT, (JogDirection.WEST, JogDirection.SOUTH)),
        (StartCorner.BOTTOM_LEFT, (JogDirection.EAST, JogDirection.NORTH)),
        (StartCorner.BOTTOM_RIGHT, (JogDirection.WEST, JogDirection.NORTH)),
    ],
)
def test_each_corner_names_the_way_the_job_grows(corner, directions):
    assert corner.toward_opposite == directions


def test_the_directions_come_from_calculate_jog(machine):
    """One mapping site: flip the arrows and the pre-move follows."""
    panel = machine.panel
    before = panel.start_corner_offset(StartCorner.TOP_LEFT, WIDTH, HEIGHT)
    real = MachinePanel.calculate_jog

    def flipped(self, direction, distance):
        return {
            axis: -delta
            for axis, delta in real(self, direction, distance).items()
        }

    with patch.object(MachinePanel, "calculate_jog", flipped):
        after = panel.start_corner_offset(StartCorner.TOP_LEFT, WIDTH, HEIGHT)

    # Every axis that ran negative now runs positive and vice versa,
    # so each component swaps between 0 and minus the extent.
    assert (before[0] + after[0], before[1] + after[1]) == (-WIDTH, -HEIGHT)
