"""
Imported layers named for what they do ("cut", "scan 3mm mdf",
"engrave") become layers with that step, the recipe their material
and thickness have on the active machine, in the order engrave, scan,
cut, through FileCmd's real import path.
"""

import asyncio
import time
from pathlib import Path

import pytest
import pytest_asyncio

from swiftcut import config
from swiftcut.core.layer import Layer
from swiftcut.core.recipe_manager import RecipeManager
from swiftcut.core.vectorization_spec import (
    LayerImportMode,
    LayerSource,
    PassthroughSpec,
    TraceSpec,
)
from swiftcut.doceditor.import_materializer import (
    ImportGrouping,
    ImportOptions,
    names_apply,
)

# Read at import, before the autouse no_builtin_recipe_sync fixture
# clears it for each test.
SHIPPED_DEFAULTS = config.BUILTIN_RECIPES_FILE

TESTS_DIR = Path(__file__).parent.parent
NAMED = TESTS_DIR / "fixtures" / "import" / "layer_names.svg"
NAMED_IDS = ["cut", "scan_3mm_mdf", "engrave", "Layer_1"]
BY_SOURCE = ImportOptions(grouping=ImportGrouping.BY_SOURCE)


async def _wait_for_import(editor, task_mgr, timeout=60.0):
    """Waits until the import task and the pipeline are done."""
    deadline = time.monotonic() + timeout
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "import did not finish"
        await asyncio.sleep(0.01)
    await editor.wait_until_settled()


def _lab_machine(context, name):
    """A machine of that name on the inert NoDeviceDriver."""
    from swiftcut.machine.models.machine import Laser, Machine

    machine = Machine(context)
    machine.name = name
    machine.driver_name = "NoDeviceDriver"
    machine.set_axis_extents(1400, 900)
    machine.heads.clear()
    machine.add_head(Laser())
    context.machine_mgr.add_machine(machine)
    return machine


@pytest_asyncio.fixture
async def machines(doc_editor, task_mgr):
    """ilab-614 (active) and ilab-626."""
    context = doc_editor.context
    result = {
        name: _lab_machine(context, name) for name in ("ilab-614", "ilab-626")
    }
    context.config.set_machine(result["ilab-614"])
    yield result
    # A switch rebuilds the pipeline after its debounce: wait for the
    # rebuild, not only for the tasks already running.
    assert await asyncio.to_thread(doc_editor.wait_until_settled_sync, 10)
    await asyncio.to_thread(task_mgr.wait_until_settled, 10000)


@pytest.fixture
def lab_recipes(doc_editor, tmp_path, monkeypatch):
    """The shipped lab recipes, in a private directory."""
    mgr = RecipeManager(tmp_path / "recipes")
    mgr.sync_builtins(SHIPPED_DEFAULTS)
    monkeypatch.setattr(doc_editor.context, "_recipe_mgr", mgr)
    return mgr


def _spec(ids=NAMED_IDS, **kwargs):
    """The dialog's spec for a file of these layers."""
    return PassthroughSpec(active_layer_ids=list(ids), **kwargs)


async def _import(editor, task_mgr, path, spec, options=BY_SOURCE):
    """Imports a file; returns the layers it added."""
    before = list(editor.doc.layers)
    editor.file.load_file_from_path(path, None, spec, options=options)
    await _wait_for_import(editor, task_mgr)
    return [layer for layer in editor.doc.layers if layer not in before]


def _steps(layer: Layer) -> list[str]:
    return [type(step).__name__ for step in layer.workflow.steps]


def _numbers(step):
    return (step.cut_speed, pytest.approx(step.power))


def _one_layer_svg(path: Path, name: str) -> Path:
    """An SVG of one layer of that name, holding a square outline."""
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="100mm" viewBox="0 0 100 100">'
        f'<g id="L1" data-name="{name}"><rect x="10" y="10" width="40" '
        'height="40" fill="none" stroke="#000"/></g></svg>'
    )
    return path


class TestBySource:
    @pytest.mark.asyncio
    async def test_layers_are_ordered_and_get_their_step(
        self, doc_editor, task_mgr, machines, lab_recipes
    ):
        """
        The file has cut, scan 3mm mdf, engrave, Layer 1: they come in
        as engrave, scan, cut, then Layer 1, each named one with its
        step alone, Layer 1 with today's default steps.
        """
        added = await _import(doc_editor, task_mgr, NAMED, _spec())

        assert [layer.name for layer in added] == [
            "engrave",
            "scan 3mm mdf",
            "cut",
            "Layer 1",
        ]
        engrave, scan, cut, plain = added
        assert _steps(engrave) == ["EngraveStep"]
        assert _steps(scan) == ["ScanStep"]
        assert _steps(cut) == ["ContourStep"]
        assert _steps(plain) == ["ContourStep"]
        assert [layer.material for layer in (engrave, cut, plain)] == [
            None,
            None,
            None,
        ]

    @pytest.mark.asyncio
    async def test_scan_3mm_mdf_takes_the_mdf_scan_recipe(
        self, doc_editor, task_mgr, machines, lab_recipes
    ):
        """
        MDF · Scan: 300 mm/s (18000 mm/min), 18 % on both machines;
        the layer remembers its material and the machine it was filled
        for, and follows a switch.
        """
        added = await _import(doc_editor, task_mgr, NAMED, _spec())
        _engrave, scan, _cut, _plain = added
        (step,) = scan.workflow.steps

        assert scan.material == ("mdf", 3.0)
        assert scan.material_machine == "ilab-614"
        assert step.applied_recipe_uid == "mdf-scan"
        assert _numbers(step) == (18000, 0.18)
        assert scan.color == "#c8a27a"

        doc_editor.context.config.set_machine(machines["ilab-626"])

        assert scan.material_machine == "ilab-626"
        assert step.applied_recipe_uid == "mdf-scan"
        assert _numbers(step) == (18000, 0.18)

    @pytest.mark.asyncio
    async def test_cut_3mm_mdf_numbers_follow_the_machine(
        self, doc_editor, task_mgr, machines, lab_recipes, tmp_path
    ):
        """
        MDF 3 mm · Cut: 30 mm/s at 50 % on the ilab-614, 35 mm/s at
        65 % on the ilab-626 (the model holds mm/min).
        """
        path = _one_layer_svg(tmp_path / "cut.svg", "cut 3mm mdf")

        (layer,) = await _import(doc_editor, task_mgr, path, _spec(["L1"]))
        (step,) = layer.workflow.steps

        assert layer.material == ("mdf", 3.0)
        assert step.applied_recipe_uid == "mdf-3-cut"
        assert _numbers(step) == (1800, 0.50)
        assert layer.color == "#a0693a"

        doc_editor.context.config.set_machine(machines["ilab-626"])

        assert layer.material_machine == "ilab-626"
        assert _numbers(step) == (2100, 0.65)

    @pytest.mark.asyncio
    async def test_a_name_without_a_recipe_gets_the_step_defaults(
        self, doc_editor, task_mgr, machines, lab_recipes, tmp_path
    ):
        """No MDF 4 mm cut is shipped: a plain Cut, no material."""
        path = _one_layer_svg(tmp_path / "cut.svg", "cut 4mm mdf")

        (layer,) = await _import(doc_editor, task_mgr, path, _spec(["L1"]))

        (step,) = layer.workflow.steps
        assert type(step).__name__ == "ContourStep"
        assert layer.material is None
        assert layer.material_machine is None
        assert step.applied_recipe_uid is None

    @pytest.mark.asyncio
    async def test_one_undo_removes_everything(
        self, doc_editor, task_mgr, machines, lab_recipes
    ):
        doc = doc_editor.doc
        layers = list(doc.layers)
        first = layers[0]
        state = (first.color, first.material, _steps(first))
        history = doc_editor.history_manager
        entries = len(history.undo_stack)

        added = await _import(doc_editor, task_mgr, NAMED, _spec())

        assert len(added) == 4
        assert len(history.undo_stack) == entries + 1

        history.undo()

        assert doc.layers == layers
        assert doc.all_workpieces == []
        assert (first.color, first.material, _steps(first)) == state


class TestModes:
    @pytest.mark.asyncio
    async def test_map_to_existing_keeps_named_layers_apart(
        self, doc_editor, task_mgr, machines, lab_recipes
    ):
        """
        With four document layers, a named source layer is a new layer
        all the same; Layer 1 (fourth) goes into the fourth layer, as
        Map to Existing pours it.
        """
        doc = doc_editor.doc
        for i in range(3):
            doc.add_child(Layer(name=f"Existing {i}"))
        existing = list(doc.layers)
        spec = _spec(layer_import_mode=LayerImportMode.MAP_TO_EXISTING)
        options = ImportOptions(grouping=ImportGrouping.SINGLE)

        added = await _import(doc_editor, task_mgr, NAMED, spec, options)

        assert [layer.name for layer in added] == [
            "engrave",
            "scan 3mm mdf",
            "cut",
        ]
        assert [_steps(layer) for layer in added] == [
            ["EngraveStep"],
            ["ScanStep"],
            ["ContourStep"],
        ]
        assert doc.layers == existing + added
        assert [len(layer.all_workpieces) for layer in existing] == [
            0,
            0,
            0,
            1,
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "options",
        [
            ImportOptions(grouping=ImportGrouping.SINGLE),
            ImportOptions(
                grouping=ImportGrouping.BY_SOURCE,
                layer_per_source_layer=False,
            ),
        ],
        ids=["flatten", "by-source-one-layer"],
    )
    async def test_flatten_applies_no_names(
        self, doc_editor, task_mgr, machines, lab_recipes, options
    ):
        """
        Flatten, or By source without a layer per source layer: all on
        the current layer, which gets today's default steps if it has
        none.
        """
        doc = doc_editor.doc
        layers = list(doc.layers)
        steps = _steps(doc.active_layer)
        spec = _spec(layer_import_mode=LayerImportMode.FLATTEN)

        added = await _import(doc_editor, task_mgr, NAMED, spec, options)

        assert added == []
        assert doc.layers == layers
        assert doc.active_layer.all_workpieces
        assert _steps(doc.active_layer) == (steps or ["ContourStep"])
        assert doc.active_layer.material is None

    @pytest.mark.parametrize(
        "spec, applies",
        [
            (PassthroughSpec(), True),
            (
                PassthroughSpec(layer_import_mode=LayerImportMode.NEW_LAYERS),
                True,
            ),
            (
                PassthroughSpec(layer_import_mode=LayerImportMode.FLATTEN),
                False,
            ),
            (PassthroughSpec(layer_source=LayerSource.COLORS), False),
            (TraceSpec(), False),
            (None, False),
        ],
        ids=["map", "new", "flatten", "colors", "trace", "none"],
    )
    def test_names_apply_where_source_layers_stay_layers(self, spec, applies):
        assert names_apply(spec) is applies


class TestOverrides:
    @pytest.mark.asyncio
    async def test_the_chosen_operation_wins_over_the_name(
        self, doc_editor, task_mgr, machines, lab_recipes
    ):
        """
        cut made Engrave, Layer 1 made Cut, engrave made No operation:
        engrave layers (cut), scan, cut (Layer 1), then engrave with
        today's default steps.
        """
        options = ImportOptions(
            grouping=ImportGrouping.BY_SOURCE,
            layer_operations={
                "cut": "engrave",
                "Layer_1": "cut",
                "engrave": None,
            },
        )

        added = await _import(doc_editor, task_mgr, NAMED, _spec(), options)

        assert [layer.name for layer in added] == [
            "cut",
            "scan 3mm mdf",
            "Layer 1",
            "engrave",
        ]
        assert [_steps(layer) for layer in added] == [
            ["EngraveStep"],
            ["ScanStep"],
            ["ContourStep"],
            ["ContourStep"],
        ]


class TestInteriorLayer:
    @pytest.mark.asyncio
    async def test_counts_as_an_engrave_layer(
        self, doc_editor, task_mgr, machines, lab_recipes, tmp_path
    ):
        """
        A cut layer of a frame with a dot inside, its interior on a
        layer of its own: the interior layer comes in before the cut.
        """
        path = tmp_path / "frame.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
            'height="100mm" viewBox="0 0 100 100"><g id="cut">'
            '<rect x="10" y="10" width="80" height="80" fill="none" '
            'stroke="#f00"/><circle cx="50" cy="50" r="5" fill="#000"/>'
            "</g></svg>"
        )
        options = ImportOptions(
            grouping=ImportGrouping.PIECES, interior_on_own_layer=True
        )

        added = await _import(
            doc_editor, task_mgr, path, _spec(["cut"]), options
        )

        assert [layer.name for layer in added] == ["frame engrave", "cut"]
        assert [_steps(layer) for layer in added] == [
            ["EngraveStep"],
            ["ContourStep"],
        ]
