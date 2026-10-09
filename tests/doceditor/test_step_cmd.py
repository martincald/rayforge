import asyncio
import threading

import pytest
import pytest_asyncio

from swiftcut import config
from swiftcut.core.doc import Doc
from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import RecipeManager
from swiftcut.core.step import Step
from swiftcut.doceditor.step_cmd import StepCmd

# Read at import, before the autouse no_builtin_recipe_sync fixture
# clears it for each test.
SHIPPED_DEFAULTS = config.BUILTIN_RECIPES_FILE


@pytest.fixture
def step_cmd(doc_editor):
    """Provides a StepCmd instance."""
    return StepCmd(doc_editor)


@pytest.fixture
def recipe_mgr(doc_editor, tmp_path, monkeypatch):
    """A RecipeManager on a private directory, used by the context."""
    mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(doc_editor.context, "_recipe_mgr", mgr)
    return mgr


def test_apply_best_recipe_colors_the_given_layer(
    step_cmd, doc_editor, recipe_mgr
):
    """A recipe color reaches the layer passed in, undoably."""
    recipe = Recipe(name="Red", color="#ff0000", settings={"power": 0.4})
    recipe_mgr.add_recipe(recipe)
    layer = doc_editor.doc.layers[0]
    old_color = layer.color
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step, layer=layer)

    assert step.applied_recipe_uid == recipe.uid
    assert layer.color == "#ff0000"
    doc_editor.history_manager.undo()
    assert layer.color == old_color


def test_apply_best_recipe_without_layer_leaves_colors(
    step_cmd, doc_editor, recipe_mgr
):
    """Without a layer, applying a colored recipe changes no layer."""
    recipe = Recipe(name="Red", color="#ff0000")
    recipe_mgr.add_recipe(recipe)
    colors = [layer.color for layer in doc_editor.doc.layers]
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step)

    assert step.applied_recipe_uid == recipe.uid
    assert [layer.color for layer in doc_editor.doc.layers] == colors
    assert not doc_editor.history_manager.can_undo()


def test_apply_best_recipe_without_color_leaves_layer(
    step_cmd, doc_editor, recipe_mgr
):
    """A legacy recipe without a color leaves the layer color alone."""
    recipe = Recipe(name="Plain")
    recipe_mgr.add_recipe(recipe)
    layer = doc_editor.doc.layers[0]
    old_color = layer.color
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step, layer=layer)

    assert step.applied_recipe_uid == recipe.uid
    assert layer.color == old_color
    assert not doc_editor.history_manager.can_undo()


def test_set_step_param(step_cmd):
    """Test setting a step parameter."""
    target_dict = {}
    key = "test_key"
    new_value = "test_value"
    name = "Test Command"

    step_cmd.set_step_param(target_dict, key, new_value, name)

    assert target_dict[key] == new_value


def test_set_step_param_no_change(step_cmd):
    """Test that setting the same value does nothing."""
    target_dict = {"test_key": "test_value"}
    key = "test_key"
    new_value = "test_value"
    name = "Test Command"

    step_cmd.set_step_param(target_dict, key, new_value, name)

    assert target_dict[key] == new_value


def test_set_step_param_float_tolerance(step_cmd):
    """Test that setting a float value within tolerance does nothing."""
    target_dict = {"test_key": 1.0}
    key = "test_key"
    new_value = 1.0000001  # Within 1e-6 tolerance
    name = "Test Command"

    step_cmd.set_step_param(target_dict, key, new_value, name)

    assert target_dict[key] == 1.0


def test_synced_builtin_color_reaches_the_layer(
    step_cmd, doc_editor, tmp_path, monkeypatch
):
    """A bundled recipe's color survives the sync and colors the layer."""
    bundle = tmp_path / "defaults.yaml"
    bundle.write_text(
        "version: 1\n"
        "recipes:\n"
        "- {uid: builtin-red, name: Red, color: '#FF0000'}\n"
    )
    RecipeManager(tmp_path / "recipes", bundle)
    recipe_mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(doc_editor.context, "_recipe_mgr", recipe_mgr)
    layer = doc_editor.doc.layers[0]
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step, layer=layer)

    assert recipe_mgr.recipes["builtin-red"].builtin
    assert step.applied_recipe_uid == "builtin-red"
    assert layer.color == "#ff0000"


# --- Material presets: per machine, applied to a layer ---------------

MDF = ("mdf", 3.0)

MDF_CUT = {
    "ilab-614": {"power": 0.6, "min_power": 0.5, "cut_speed": 1200},
    "ilab-626": {"power": 0.65, "min_power": 0.55, "cut_speed": 1000},
}
MDF_ENGRAVE = {
    "ilab-614": {"power": 0.25, "min_power": 0.15, "cut_speed": 18000},
    "ilab-626": {"power": 0.3, "min_power": 0.2, "cut_speed": 15000},
}
ENGRAVE_SETTINGS = {
    "engrave_mode": "OUTLINE",
    "scan_angle": 45.0,
    "depth_mode": "CONSTANT_POWER",
    "invert": True,
}


def _material_recipe(uid, step_type, color, settings, machine_settings):
    return Recipe(
        uid=uid,
        name=uid,
        color=color,
        target_step_types=[step_type],
        material_uid="mdf",
        min_thickness_mm=3.0,
        max_thickness_mm=3.0,
        settings=settings,
        machine_settings=machine_settings,
    )


@pytest.fixture
def mdf_recipes(recipe_mgr):
    """MDF 3 mm recipes for Contour and Engrave, per lab machine."""
    recipe_mgr.add_recipe(
        _material_recipe("mdf-cut", "ContourStep", "#cc6600", {}, MDF_CUT)
    )
    recipe_mgr.add_recipe(
        _material_recipe(
            "mdf-engrave",
            "EngraveStep",
            "#3366ff",
            dict(ENGRAVE_SETTINGS),
            MDF_ENGRAVE,
        )
    )
    return recipe_mgr


def _lab_machine(context, name):
    """A machine of that name on the inert NoDeviceDriver."""
    from swiftcut.machine.models.machine import Laser, Machine

    machine = Machine(context)
    machine.name = name
    machine.driver_name = "NoDeviceDriver"
    machine.heads.clear()
    machine.add_head(Laser())
    context.machine_mgr.add_machine(machine)
    return machine


@pytest_asyncio.fixture
async def machines(doc_editor, task_mgr):
    """ilab-614 (active), ilab-626 and an unknown machine."""
    context = doc_editor.context
    result = {
        name: _lab_machine(context, name)
        for name in ("ilab-614", "ilab-626", "Default Machine")
    }
    context.config.set_machine(result["ilab-614"])
    yield result
    # A switch rebuilds the pipeline after its debounce: wait for the
    # rebuild, not only for the tasks already running.
    assert await asyncio.to_thread(doc_editor.wait_until_settled_sync, 10)
    await asyncio.to_thread(task_mgr.wait_until_settled, 10000)


@pytest.fixture
def layer_steps(doc_editor, contour_step_class, engrave_step_class):
    """The first layer, holding a Contour and an Engrave step."""
    layer = doc_editor.doc.layers[0]
    for step in list(layer.workflow.steps):
        layer.workflow.remove_step(step)
    contour = contour_step_class.create(doc_editor.context)
    engrave = engrave_step_class.create(doc_editor.context)
    layer.workflow.add_step(contour)
    layer.workflow.add_step(engrave)
    doc_editor.history_manager.clear()
    return layer, contour, engrave


def _numbers(step):
    return {
        "power": step.power,
        "min_power": step.min_power,
        "cut_speed": step.cut_speed,
    }


def _engrave_settings(step):
    return {key: getattr(step, key) for key in ENGRAVE_SETTINGS}


def _snapshot(layer, contour, engrave):
    return (
        layer.material,
        layer.color,
        _numbers(contour),
        _numbers(engrave),
        _engrave_settings(engrave),
        contour.applied_recipe_uid,
        engrave.applied_recipe_uid,
    )


def test_picking_a_material_fills_every_step_for_the_active_machine(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps

    step_cmd.apply_material(layer, MDF)

    assert layer.material == MDF
    assert _numbers(contour) == MDF_CUT["ilab-614"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-614"]
    assert _engrave_settings(engrave) == ENGRAVE_SETTINGS
    assert contour.applied_recipe_uid == "mdf-cut"
    assert engrave.applied_recipe_uid == "mdf-engrave"
    # The layer takes the color of the recipe applied to its first step.
    assert layer.color == "#cc6600"


def test_picking_a_material_is_one_undo_step(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    before = _snapshot(layer, contour, engrave)

    step_cmd.apply_material(layer, MDF)

    history = doc_editor.history_manager
    assert len(history.undo_stack) == 1
    history.undo()
    assert _snapshot(layer, contour, engrave) == before
    assert not history.can_undo()
    history.redo()
    assert layer.material == MDF
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-614"]


def test_switching_machine_reapplies_its_numbers_outside_history(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    before = _snapshot(layer, contour, engrave)
    step_cmd.apply_material(layer, MDF)
    history = doc_editor.history_manager
    updated = []
    contour.updated.connect(lambda sender: updated.append(sender), weak=False)

    doc_editor.context.config.set_machine(machines["ilab-626"])

    assert _numbers(contour) == MDF_CUT["ilab-626"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-626"]
    assert _engrave_settings(engrave) == ENGRAVE_SETTINGS
    assert updated
    assert len(history.undo_stack) == 1

    doc_editor.context.config.set_machine(machines["ilab-614"])

    assert _numbers(contour) == MDF_CUT["ilab-614"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-614"]
    assert len(history.undo_stack) == 1

    # Undoing the pick on 626 restores what the steps had before it,
    # never the other machine's numbers.
    doc_editor.context.config.set_machine(machines["ilab-626"])
    history.undo()
    assert _snapshot(layer, contour, engrave) == before


def test_switching_machine_overwrites_hand_edits(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, _ = layer_steps
    step_cmd.apply_material(layer, MDF)
    contour.power = 0.95

    doc_editor.context.config.set_machine(machines["ilab-626"])

    assert contour.power == MDF_CUT["ilab-626"]["power"]


def test_an_unknown_machine_gets_the_shared_settings_only(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    step_cmd.apply_material(layer, MDF)
    engrave.scan_angle = 0.0

    doc_editor.context.config.set_machine(machines["Default Machine"])

    assert _numbers(contour) == MDF_CUT["ilab-614"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-614"]
    assert engrave.scan_angle == ENGRAVE_SETTINGS["scan_angle"]


def test_a_layer_without_material_is_left_alone_on_switch(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    before = _snapshot(layer, contour, engrave)

    doc_editor.context.config.set_machine(machines["ilab-626"])

    assert _snapshot(layer, contour, engrave) == before


def test_a_config_change_that_is_not_a_switch_reapplies_nothing(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, _ = layer_steps
    step_cmd.apply_material(layer, MDF)
    contour.power = 0.95

    doc_editor.context.config.set_theme("dark")

    assert contour.power == 0.95


def test_manual_forgets_the_material_and_keeps_the_steps(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    step_cmd.apply_material(layer, MDF)
    history = doc_editor.history_manager
    filled = _snapshot(layer, contour, engrave)[1:]

    step_cmd.apply_material(layer, None)

    assert layer.material is None
    assert _snapshot(layer, contour, engrave)[1:] == filled
    assert len(history.undo_stack) == 2
    doc_editor.context.config.set_machine(machines["ilab-626"])
    assert _numbers(contour) == MDF_CUT["ilab-614"]
    history.undo()
    assert layer.material == MDF


def test_picking_the_same_material_again_adds_no_undo_step(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, _, _ = layer_steps
    step_cmd.apply_material(layer, MDF)

    step_cmd.apply_material(layer, MDF)

    assert len(doc_editor.history_manager.undo_stack) == 1


def test_a_new_step_on_a_material_layer_gets_the_materials_recipe(
    step_cmd,
    doc_editor,
    machines,
    mdf_recipes,
    layer_steps,
    engrave_step_class,
):
    layer, _, _ = layer_steps
    # A generic recipe would win without the layer's material.
    mdf_recipes.add_recipe(Recipe(uid="generic", settings={"power": 1.0}))
    step_cmd.apply_material(layer, MDF)
    step = engrave_step_class.create(doc_editor.context)

    step_cmd.apply_best_recipe_to_step(step, layer=layer)

    assert step.applied_recipe_uid == "mdf-engrave"
    assert _numbers(step) == MDF_ENGRAVE["ilab-614"]
    assert _engrave_settings(step) == ENGRAVE_SETTINGS


def test_a_new_step_without_a_material_recipe_falls_back(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, _, _ = layer_steps
    mdf_recipes.add_recipe(Recipe(uid="generic", settings={"power": 1.0}))
    step_cmd.apply_material(layer, MDF)
    step = Step(typelabel="Test")

    step_cmd.apply_best_recipe_to_step(step, layer=layer)

    assert step.applied_recipe_uid == "generic"


# --- A material label always means the active machine's numbers ------


def _stacks(history):
    return len(history.undo_stack), len(history.redo_stack)


def _layer_dicts(data):
    return [c for c in data["children"] if c.get("type") == "layer"]


def test_a_redo_after_a_switch_takes_the_active_machines_numbers(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    doc_editor.context.config.set_machine(machines["ilab-626"])
    history = doc_editor.history_manager
    history.undo()

    history.redo()

    assert layer.material == MDF
    assert layer.material_machine == "ilab-626"
    assert _numbers(contour) == MDF_CUT["ilab-626"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-626"]
    assert _stacks(history) == (1, 0)


def test_undoing_manual_after_a_switch_takes_the_active_machines_numbers(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    step_cmd.apply_material(layer, None)
    assert layer.material_machine is None
    doc_editor.context.config.set_machine(machines["ilab-626"])
    # "Manual" is set by hand: the switch leaves it alone.
    assert _numbers(contour) == MDF_CUT["ilab-614"]

    doc_editor.history_manager.undo()

    assert layer.material == MDF
    assert layer.material_machine == "ilab-626"
    assert _numbers(contour) == MDF_CUT["ilab-626"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-626"]


def test_a_document_filled_on_614_opens_on_626_with_its_numbers(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, _, _ = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    data = doc_editor.doc.to_dict()
    assert _layer_dicts(data)[0]["material_machine"] == "ilab-614"
    doc_editor.context.config.set_machine(machines["ilab-626"])

    doc_editor.set_doc(Doc.from_dict(data))

    opened = doc_editor.doc.layers[0]
    contour, engrave = opened.workflow.steps
    assert opened.material == MDF
    assert opened.material_machine == "ilab-626"
    assert _numbers(contour) == MDF_CUT["ilab-626"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-626"]
    assert _stacks(doc_editor.history_manager) == (0, 0)


def test_a_document_filled_here_keeps_its_hand_edits_on_open(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, _ = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    contour.power = 0.95
    new_doc = Doc.from_dict(doc_editor.doc.to_dict())
    opened_contour = new_doc.layers[0].workflow.steps[0]
    updated = []
    opened_contour.updated.connect(updated.append, weak=False)

    doc_editor.set_doc(new_doc)

    assert opened_contour.power == 0.95
    assert updated == []


def test_a_document_without_the_fill_machine_is_filled_on_open(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    """A document saved before material_machine existed: the machine
    its steps were filled for is unknown, so they are filled again."""
    layer, contour, _ = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    contour.power = 0.95
    data = doc_editor.doc.to_dict()
    del _layer_dicts(data)[0]["material_machine"]

    doc_editor.set_doc(Doc.from_dict(data))

    opened = doc_editor.doc.layers[0]
    assert opened.material == MDF
    assert opened.material_machine == "ilab-614"
    assert _numbers(opened.workflow.steps[0]) == MDF_CUT["ilab-614"]
    assert opened.extra == {}


def test_opening_a_project_filled_on_another_machine_stays_saved(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps, tmp_path
):
    """The re-fill on open never marks the document unsaved: the file
    fills the same numbers again whenever it is opened there."""
    layer, _, _ = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    path = tmp_path / "mdf.ryp"
    assert doc_editor.file.save_project_to_path(path)
    doc_editor.context.config.set_machine(machines["ilab-626"])

    assert doc_editor.file.load_project_from_path(path)

    contour = doc_editor.doc.layers[0].workflow.steps[0]
    assert _numbers(contour) == MDF_CUT["ilab-626"]
    assert doc_editor.is_saved
    assert _stacks(doc_editor.history_manager) == (0, 0)


def test_refills_add_no_undo_entries(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, _, _ = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    history = doc_editor.history_manager
    config = doc_editor.context.config

    config.set_machine(machines["ilab-626"])
    assert _stacks(history) == (1, 0)
    history.undo()
    assert _stacks(history) == (0, 1)
    history.redo()  # re-filled for ilab-626
    assert layer.material_machine == "ilab-626"
    assert _stacks(history) == (1, 0)
    config.set_machine(machines["ilab-614"])
    assert _stacks(history) == (1, 0)

    data = doc_editor.doc.to_dict()
    config.set_machine(machines["ilab-626"])
    doc_editor.set_doc(Doc.from_dict(data))  # re-filled for ilab-626
    assert doc_editor.doc.layers[0].material_machine == "ilab-626"
    assert _stacks(doc_editor.history_manager) == (0, 0)


def test_a_refill_that_changes_nothing_sends_nothing(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    layer.material_machine = None
    sent = []
    for step in (contour, engrave):
        step.updated.connect(sent.append, weak=False)
        step.per_step_transformer_changed.connect(sent.append, weak=False)

    step_cmd.refill_layer_materials()

    assert layer.material_machine == "ilab-614"
    assert sent == []


def test_a_refill_signals_the_per_step_transformers_it_changes(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    """Like the undoable apply, a re-fill that changes a per-step
    transformer sends the step's per-step transformer signal."""
    layer, contour, _ = layer_steps
    mdf_recipes.recipes["mdf-cut"].transformer_dicts = [
        {"name": "MultiPassTransformer", "passes": 2, "recipe_apply": True}
    ]
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    (multipass,) = [
        d
        for d in contour.per_step_transformers_dicts
        if d["name"] == "MultiPassTransformer"
    ]
    assert multipass["passes"] == 2
    multipass["passes"] = 5
    changed = []
    contour.per_step_transformer_changed.connect(changed.append, weak=False)

    doc_editor.context.config.set_machine(machines["ilab-626"])

    assert multipass["passes"] == 2
    assert len(changed) == 1

    # Back on ilab-614 only the numbers change, not the transformer.
    doc_editor.context.config.set_machine(machines["ilab-614"])

    assert _numbers(contour) == MDF_CUT["ilab-614"]
    assert len(changed) == 1


def test_a_step_the_material_has_no_recipe_for_is_named(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, contour, engrave = layer_steps
    mdf_recipes.delete_recipe("mdf-engrave")
    engrave_before = _numbers(engrave)
    messages = []

    def on_notification(sender, message, **kwargs):
        messages.append((message, threading.current_thread()))

    doc_editor.notification_requested.connect(on_notification, weak=False)

    step_cmd.apply_material(layer, MDF)

    assert _numbers(contour) == MDF_CUT["ilab-614"]
    assert _numbers(engrave) == engrave_before
    assert len(messages) == 1
    message, thread = messages[0]
    assert engrave.name in message
    assert contour.name not in message
    assert thread is threading.main_thread()

    # "Manual" fills nothing, so it names nothing.
    step_cmd.apply_material(layer, None)
    assert len(messages) == 1


def test_a_material_with_a_recipe_for_every_step_names_none(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps
):
    layer, _, _ = layer_steps
    messages = []
    doc_editor.notification_requested.connect(
        lambda sender, **kwargs: messages.append(kwargs), weak=False
    )

    step_cmd.apply_material(layer, MDF)

    assert messages == []


@pytest.mark.asyncio
async def test_a_switch_through_the_machine_manager_refills_on_main_thread(
    step_cmd, doc_editor, machines, mdf_recipes, layer_steps, task_mgr
):
    """The switcher's path: a background task that sets the machine
    on the main thread, where the layer is filled for ilab-626."""
    layer, contour, engrave = layer_steps
    step_cmd.apply_material(layer, MDF)  # on ilab-614
    threads = []
    contour.updated.connect(
        lambda sender: threads.append(threading.current_thread()),
        weak=False,
    )
    manager = doc_editor.context.machine_mgr

    assert manager.set_active_machine(machines["ilab-626"]) is True
    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)

    assert doc_editor.context.config.machine is machines["ilab-626"]
    assert threads
    assert all(thread is threading.main_thread() for thread in threads)
    assert layer.material_machine == "ilab-626"
    assert _numbers(contour) == MDF_CUT["ilab-626"]
    assert _numbers(engrave) == MDF_ENGRAVE["ilab-626"]
    assert _stacks(doc_editor.history_manager) == (1, 0)


# --- Shipped lab recipes, through the real apply path -----------------


@pytest.fixture
def lab_recipes(recipe_mgr):
    """The recipe manager, synced with the shipped lab recipes."""
    recipe_mgr.sync_builtins(SHIPPED_DEFAULTS)
    return recipe_mgr


def test_a_6_mm_mdf_pick_fills_the_contour_from_the_shipped_cut(
    step_cmd, doc_editor, machines, lab_recipes, layer_steps
):
    layer, contour, _ = layer_steps

    step_cmd.apply_material(layer, ("mdf", 6.0))

    assert contour.applied_recipe_uid == "mdf-6-cut"
    assert contour.cut_speed == 1200
    assert contour.cut_speed / 60 == 20  # mm/s in the file, mm/min here
    assert contour.power == pytest.approx(0.65)
    assert contour.min_power == pytest.approx(0.65)
    # The file says "#8B5A2B"; the app stores colors in lower case.
    assert layer.color == "#8b5a2b"

    doc_editor.context.config.set_machine(machines["ilab-626"])

    assert contour.cut_speed == 750
    assert contour.cut_speed / 60 == 12.5
    assert contour.power == pytest.approx(0.75)
    assert contour.min_power == pytest.approx(0.75)


def test_a_mdf_pick_engraves_with_the_shipped_base_engrave(
    step_cmd, doc_editor, machines, lab_recipes, layer_steps
):
    layer, _, engrave = layer_steps
    recipe = lab_recipes.recipes["mdf-engrave"]
    assert recipe.target_step_types == ["EngraveStep"]

    step_cmd.apply_material(layer, ("mdf", 6.0))

    assert engrave.applied_recipe_uid == "mdf-engrave"
    assert engrave.cut_speed == 12000
    assert engrave.power == pytest.approx(0.10)
    assert engrave.min_power == pytest.approx(0.10)


def test_the_shipped_scan_applies_to_a_contour_step(
    step_cmd, doc_editor, machines, lab_recipes, layer_steps
):
    _, contour, _ = layer_steps
    recipe = lab_recipes.recipes["mdf-scan"]
    assert recipe.target_step_types == ["ContourStep"]

    with doc_editor.history_manager.transaction("test") as t:
        step_cmd.apply_recipe(contour, recipe, t)

    assert contour.applied_recipe_uid == "mdf-scan"
    assert contour.cut_speed == 30000  # 500 mm/s
    assert contour.power == pytest.approx(0.18)
    assert contour.min_power == pytest.approx(0.18)


def test_a_material_pick_prefers_the_cut_over_the_scan(machines, lab_recipes):
    machine = machines["ilab-614"]

    def picked(material, thickness):
        recipe = lab_recipes.find_material_recipe(
            material, thickness, machine, "ContourStep"
        )
        return recipe.uid

    assert picked("mdf", 6.0) == "mdf-6-cut"
    assert picked("foamboard", 3.0) == "foamboard-3-cut"
    assert picked("mdf", 4.5) == "mdf-scan"


def test_acrylic_has_the_same_numbers_on_both_machines(
    step_cmd, doc_editor, machines, lab_recipes, layer_steps
):
    layer, contour, _ = layer_steps
    doc_editor.context.config.set_machine(machines["ilab-626"])

    step_cmd.apply_material(layer, ("acrylic", 3.0))

    assert contour.applied_recipe_uid == "acrylic-3-cut"
    assert contour.cut_speed == 1800  # 30 mm/s
    assert contour.power == pytest.approx(0.55)
