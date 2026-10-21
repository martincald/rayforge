"""
The guided tours: what each step points at, says, and waits for.

Every text says what the control does today. A step that waits for
the user also has Next, so a laser that is not connected, or a design
with nothing to cut, never holds a tour up.
"""

from gettext import gettext as _

from ...core.layer import Layer
from ...core.step import Step as WorkflowStep
from ...core.workpiece import WorkPiece
from ...machine.transport.transport import TransportStatus
from ..machine.cut_scale_dialog import CutScaleDialog
from .runner import Step, Tour


def _connected(win, status=None, **details) -> bool:
    return status == TransportStatus.CONNECTED


def _brought_in(win, origin=None, moved_from=None, **details) -> bool:
    """A shape came into the document: alone, in a group or a layer."""
    if moved_from is not None or origin is None:
        return False
    return isinstance(origin, WorkPiece) or bool(
        origin.get_descendants(of_type=WorkPiece)
    )


def _material_picked(win, origin=None, **details) -> bool:
    return isinstance(origin, Layer) and origin.material is not None


def _moved_to_another_layer(
    win, moved_from=None, parent_of_origin=None, **details
) -> bool:
    # Taken out of a group into its layer is an ungroup, not a move.
    return (
        isinstance(moved_from, Layer)
        and isinstance(parent_of_origin, Layer)
        and moved_from is not parent_of_origin
    )


def _step_switched_on(win, origin=None, **details) -> bool:
    return isinstance(origin, WorkflowStep) and origin.visible


def _cut_scale_asked(win, window=None, **details) -> bool:
    return isinstance(window, CutScaleDialog)


_CONNECT_FIRST = _("It turns on once the laser is connected.")
_NEEDS_A_JOB = _(
    "It turns on once the laser is connected and the design has "
    "something to cut."
)
_NO_MACHINE = _("The start corner shows once a machine is set up.")

FIRST_CUT = Tour(
    id="first-cut",
    title=_("Your First Cut"),
    steps=(
        Step(
            _("Connect by USB"),
            _(
                "Plug the laser's USB cable into this computer and switch "
                "the laser on. SwiftCut connects by itself, and the jog "
                "pad turns on."
            ),
            target="jog.pad",
            advance_on=("connection",),
            done=_connected,
            connection_status=True,
        ),
        Step(
            _("Open or draw something"),
            _(
                "Drop an SVG or DXF file on the canvas, or right-click it "
                "and choose Import File… or New Sketch to draw your own."
            ),
            target="canvas",
            advance_on=("doc-added",),
            done=_brought_in,
        ),
        Step(
            _("A layer and its steps"),
            _(
                "This card is a layer: its shapes, its material and its "
                "workflow. Each icon in the workflow row is a step, such "
                "as Cut or Engrave; click one to set its speed and power."
            ),
            target="layers.active-card",
        ),
        Step(
            _("Pick a material"),
            _(
                "Choose the material and thickness you are cutting. Its "
                "recipes for this machine fill in the layer's steps."
            ),
            target="layers.active-material",
            advance_on=("doc-updated",),
            done=_material_picked,
        ),
        Step(
            _("Start corner"),
            _(
                "The job starts where the laser head is. Pick the corner "
                "of your design that sits there; the job grows from it "
                "toward the opposite corner."
            ),
            target="dock.start-corner",
            advance_on=("machine",),
            unavailable=_NO_MACHINE,
        ),
        Step(
            _("Go Scale"),
            _(
                "Go Scale moves the head around your design's outline "
                "with the laser off, so you can see where it will cut."
            ),
            target="jog.go-scale",
            unavailable=_NEEDS_A_JOB,
        ),
        Step(
            _("Start"),
            _(
                "Start sends the job and the laser cuts it. Pause and "
                "Stop stay in reach while it runs."
            ),
            target="jog.start",
            advance_on=("start",),
            unavailable=_CONNECT_FIRST,
        ),
    ),
)

LAYERS = Tour(
    id="layers",
    title=_("Layers Explained"),
    steps=(
        Step(
            _("What a layer is"),
            _(
                "Each card here is a layer: a set of shapes, the material "
                "they are cut from, and the steps that cut them."
            ),
            target="layers.tab",
        ),
        Step(
            _("Move a shape to a layer"),
            _(
                "Drag a shape's row from one card onto another to move it "
                "to that layer. The + button adds a layer."
            ),
            target="layers.tab",
            advance_on=("doc-added",),
            done=_moved_to_another_layer,
        ),
        Step(
            _("Switch a step off"),
            _(
                "A step that is switched off is left out of the job. Try "
                "it: switch this one off, then on again."
            ),
            target="pane.step-switch",
            advance_on=("doc-updated",),
            done=_step_switched_on,
            unavailable=_(
                "The active layer has no steps yet; for a layer that has "
                "some, each shows a switch here."
            ),
        ),
        Step(
            _("A hidden layer is still cut"),
            _(
                "The eye takes a layer off the canvas: its shapes can't "
                "be selected, and nothing can be pasted or duplicated "
                "into it. It is still cut when you press Start; to leave "
                "it out of the job, switch its steps off."
            ),
            target="layers.active-eye",
        ),
        Step(
            _("Engrave, then cut"),
            _(
                "Layers run left to right, in the order of their cards, "
                "and each layer's steps run in the order shown. Put the "
                "engraving on a layer left of the cut; drag a card by its "
                "header to reorder."
            ),
            target="layers.tab",
        ),
    ),
)

POSITIONING = Tour(
    id="positioning",
    title=_("Positioning"),
    steps=(
        Step(
            _("Jog the head"),
            _(
                "Click an arrow to move the laser head by the Jog "
                "Distance, or hold it down to move until you let go. The "
                "arrows work once the laser is connected."
            ),
            target="jog.pad",
            advance_on=("jog",),
        ),
        Step(
            _("Home"),
            _("Home sends the head to the machine's home position."),
            target="jog.home",
            advance_on=("home",),
            unavailable=_CONNECT_FIRST,
        ),
        Step(
            _("Start corner"),
            _(
                "Jog the head to a corner of your stock, then pick the "
                "matching corner here. The job starts at the head and "
                "grows toward the opposite corner."
            ),
            target="dock.start-corner",
            advance_on=("machine",),
            unavailable=_NO_MACHINE,
        ),
        Step(
            _("Cut Scale"),
            _(
                "Cut Scale cuts a rectangle around your design to mark it "
                "on the stock: the laser fires. Press it to see its "
                "settings; Cancel there is fine."
            ),
            target="jog.cut-scale",
            advance_on=("window",),
            done=_cut_scale_asked,
            unavailable=_NEEDS_A_JOB,
        ),
    ),
)

TOURS: dict[str, Tour] = {
    tour.id: tour for tour in (FIRST_CUT, LAYERS, POSITIONING)
}
