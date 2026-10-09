"""The layer card's Material picker.

A row between the card's header and its operations lists "Manual"
and each material and thickness the recipes are made for. Picking one
fills the layer's steps for the active machine in one undo step, and
the picker follows undo and redo.
"""

from types import SimpleNamespace

import pytest

from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import RecipeManager

pytestmark = pytest.mark.ui

MDF = ("mdf", 3.0)


def _settle(widget):
    from gi.repository import GLib

    context = GLib.MainContext.default()
    for _ in range(200):
        while context.pending():
            context.iteration(False)
        if widget.get_height() > 0:
            break


def _recipe(uid, material, step_type, color, machine, power, speed):
    return Recipe(
        uid=uid,
        name=uid,
        color=color,
        target_step_types=[step_type],
        material_uid=material,
        min_thickness_mm=3.0,
        max_thickness_mm=3.0,
        machine_settings={
            machine: {"power": power, "cut_speed": speed},
            "elsewhere": {"power": 0.01, "cut_speed": 1},
        },
    )


@pytest.fixture
def setup(ui_context_initializer, ui_task_mgr, tmp_path, monkeypatch):
    """An editor whose first layer holds a Contour and an Engrave step,
    and recipes for MDF and acrylic on the active machine."""
    from gi.repository import Gtk

    from swiftcut.core.step_registry import step_registry
    from swiftcut.doceditor.editor import DocEditor
    from swiftcut.ui_gtk.doceditor.layers_tab import LayersTab

    context = ui_context_initializer
    recipe_mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(context, "_recipe_mgr", recipe_mgr)
    machine = context.machine.name
    for uid, material, step_type, color, power, speed in (
        ("mdf-cut", "mdf", "ContourStep", "#cc6600", 0.6, 1200),
        ("mdf-engrave", "mdf", "EngraveStep", "#3366ff", 0.25, 9000),
        ("acrylic-cut", "acrylic", "ContourStep", "#cc3366", 0.7, 600),
        ("cork-cut", "cork-x", "ContourStep", None, 0.5, 900),
    ):
        recipe_mgr.add_recipe(
            _recipe(uid, material, step_type, color, machine, power, speed)
        )

    editor = DocEditor(task_manager=ui_task_mgr, context=context)
    layer = editor.doc.layers[0]
    for step in list(layer.workflow.steps):
        layer.workflow.remove_step(step)
    contour = step_registry.get("ContourStep").create(context)
    engrave = step_registry.get("EngraveStep").create(context)
    layer.workflow.add_step(contour)
    layer.workflow.add_step(engrave)
    editor.history_manager.clear()

    tab = LayersTab(editor)
    window = Gtk.Window(child=tab, default_width=900, default_height=400)
    window.present()
    column = tab._columns[0]
    _settle(column)
    try:
        yield SimpleNamespace(
            history=editor.history_manager,
            column=column,
            picker=column.material_picker,
            layer=layer,
            contour=contour,
            engrave=engrave,
        )
    finally:
        window.destroy()
        editor.cleanup()


def _labels(picker):
    model = picker.get_model()
    return [model.get_string(i) for i in range(model.get_n_items())]


def test_the_card_has_a_material_row_under_its_header(setup):
    column = setup.column

    rows = []
    child = column.card.get_first_child()
    while child is not None:
        rows.append(child)
        child = child.get_next_sibling()

    assert rows[0] is column.header
    assert setup.picker.get_parent() is rows[1]
    assert rows[2] is column.workflow_row


def test_the_picker_lists_manual_then_each_material_and_thickness(setup):
    from swiftcut.context import get_context

    picker = setup.picker
    material_mgr = get_context().material_mgr

    assert picker.choices == [
        None,
        ("acrylic", 3.0),
        ("cork-x", 3.0),
        ("mdf", 3.0),
    ]
    assert _labels(picker) == [
        "Manual",
        f"3.00 mm {material_mgr.get_material('acrylic').name}",
        # A material the library does not know shows its uid.
        "3.00 mm cork-x",
        f"3.00 mm {material_mgr.get_material('mdf').name}",
    ]
    assert picker.get_selected() == 0


def test_a_long_label_does_not_widen_the_card(setup):
    from gi.repository import Gtk

    picker = setup.picker

    picker.set_selected(picker.choices.index(MDF))
    _settle(picker)
    minimum, natural, _, _ = picker.measure(Gtk.Orientation.HORIZONTAL, -1)

    assert minimum < natural


def test_picking_fills_the_layer_and_follows_undo(setup):
    picker, history, layer = setup.picker, setup.history, setup.layer
    contour, engrave = setup.contour, setup.engrave
    mdf = picker.choices.index(MDF)
    old_color = layer.color
    old_power = contour.power

    picker.set_selected(mdf)

    assert layer.material == MDF
    assert (contour.power, contour.cut_speed) == (0.6, 1200)
    assert (engrave.power, engrave.cut_speed) == (0.25, 9000)
    assert layer.color == "#cc6600"
    assert len(history.undo_stack) == 1

    history.undo()

    assert picker.get_selected() == 0
    assert layer.material is None
    assert layer.color == old_color
    assert contour.power == old_power

    history.redo()

    assert picker.get_selected() == mdf
    assert layer.material == MDF


def test_manual_forgets_the_material_and_keeps_the_settings(setup):
    picker, layer, contour = setup.picker, setup.layer, setup.contour
    picker.set_selected(picker.choices.index(MDF))

    picker.set_selected(0)

    assert layer.material is None
    assert (contour.power, contour.cut_speed) == (0.6, 1200)
    assert picker.get_selected() == 0


def test_a_layer_material_without_recipes_is_still_shown(setup):
    picker = setup.picker

    setup.layer.set_material(("plywood", 6.0))

    assert picker.choices[-1] == ("plywood", 6.0)
    assert picker.get_selected() == len(picker.choices) - 1
    assert len(setup.history.undo_stack) == 0


def test_the_picker_lists_only_materials_for_the_active_machine(setup):
    from swiftcut.context import get_context

    context = get_context()
    for uid, material, machine_id in (
        ("ply-here", "plywood", context.machine.id),
        ("cork-there", "cork-y", "another-machine"),
    ):
        recipe = _recipe(
            uid, material, "ContourStep", None, context.machine.name, 0.5, 900
        )
        recipe.target_machine_id = machine_id
        context.recipe_mgr.add_recipe(recipe)

    setup.picker.sync()

    assert ("plywood", 3.0) in setup.picker.choices
    assert ("cork-y", 3.0) not in setup.picker.choices
