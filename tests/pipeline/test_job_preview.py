"""The job preview mirrors the op stream a Start sends, timed like the
estimate.

The order tests build a real document, two layers and an engrave, a
cut and a raster, let the real Pipeline generate the job, and check
the artifact out the way MachineCmd._start_job does. The preview must
hold every moving command of those ops, in their order, and nothing
else; the ops a send hands the driver are the same ops.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import pytest_asyncio
from raygeo.geo import Geometry
from raygeo.ops import Ops
from raygeo.ops.types import CommandCategory, CommandType

from swiftcut.core.doc import Doc
from swiftcut.core.layer import Layer
from swiftcut.core.source_asset import SourceAsset
from swiftcut.core.source_asset_segment import SourceAssetSegment
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.image import SVG_RENDERER
from swiftcut.machine.cmd import MachineCmd
from swiftcut.pipeline.artifact import JobArtifact
from swiftcut.pipeline.job_preview import (
    CUT,
    ESTIMATE_TOLERANCE,
    SCAN,
    TRAVEL,
    JobPreviewModel,
)
from swiftcut.pipeline.pipeline import Pipeline

MACHINE = SimpleNamespace(
    max_cut_speed=600, max_travel_speed=3000, acceleration=1000
)


def _params(machine=MACHINE):
    return (
        machine.max_cut_speed,
        machine.max_travel_speed,
        machine.acceleration,
    )


def _moving(ops: Ops) -> list[int]:
    return [
        i for i in range(len(ops)) if ops.category(i) == CommandCategory.MOVING
    ]


def _mixed_ops() -> Ops:
    """Markers, state, every kind of move, a dwell and a zero power."""
    ops = Ops()
    ops.job_start()
    ops.layer_start("layer")
    ops.set_power(0.5)
    ops.set_feed_rate(600)
    ops.move_to(10.0, 10.0)  # 4
    ops.line_to(20.0, 10.0)  # 5
    ops.arc_to(20.0, 20.0, 0.0, 5.0, False)  # 6
    ops.dwell(500)
    ops.set_power(0.0)
    ops.line_to(10.0, 20.0)  # 9: no power, a travel
    ops.set_power(0.8)
    ops.move_to(10.0, 30.0)  # 11
    ops.scan_to(20.0, 30.0, 0.0, bytes([0, 128, 255, 128]))  # 12
    ops.layer_end("layer")
    ops.job_end()
    return ops


class TestSegments:
    def test_one_segment_per_moving_command_in_op_order(self):
        ops = _mixed_ops()

        model = JobPreviewModel.from_ops(ops, MACHINE)

        assert [s.op_index for s in model.segments] == _moving(ops)
        assert _moving(ops) == [4, 5, 6, 9, 11, 12]

    def test_kinds(self):
        model = JobPreviewModel.from_ops(_mixed_ops(), MACHINE)

        assert [s.kind for s in model.segments] == [
            TRAVEL,  # move_to
            CUT,  # line_to at 0.5
            CUT,  # arc_to at 0.5
            TRAVEL,  # line_to at zero power
            TRAVEL,  # move_to
            SCAN,  # scan_to
        ]

    def test_power_is_zero_before_the_first_set_power(self):
        ops = Ops()
        ops.move_to(0.0, 0.0)
        ops.line_to(10.0, 0.0)

        model = JobPreviewModel.from_ops(ops, MACHINE)

        assert [s.kind for s in model.segments] == [TRAVEL, TRAVEL]

    def test_an_arc_is_its_linearised_points_on_one_segment(self):
        ops = _mixed_ops()

        arc = JobPreviewModel.from_ops(ops, MACHINE).segments[2]
        line = ops.linearize(6, (20.0, 10.0, 0.0))

        assert arc.op_index == 6
        assert arc.points[0] == (20.0, 10.0)
        assert arc.points[1:] == tuple(
            line.endpoint(j)[:2] for j in range(len(line))
        )
        assert arc.points[-1] == pytest.approx((20.0, 20.0))

    def test_each_segment_starts_where_the_last_one_ended(self):
        model = JobPreviewModel.from_ops(_mixed_ops(), MACHINE)

        for before, after in zip(model.segments, model.segments[1:]):
            assert after.points[0] == before.points[-1]

    def test_the_first_move_starts_on_its_own_endpoint(self):
        """The job starts where the head is, not at the origin."""
        first = JobPreviewModel.from_ops(_mixed_ops(), MACHINE).segments[0]

        assert first.points == ((10.0, 10.0), (10.0, 10.0))
        # It keeps the time the estimate gives it.
        assert first.t1 > first.t0 == 0.0

    def test_the_source_ops_are_not_changed(self):
        ops = _mixed_ops()
        before = ops.to_dict()

        JobPreviewModel.from_ops(ops, MACHINE)

        assert ops.to_dict() == before

    def test_no_moves_no_segments(self):
        ops = Ops()
        ops.job_start()
        ops.job_end()

        model = JobPreviewModel.from_ops(ops, MACHINE)

        assert model.segments == []
        assert model.total_time == 0.0
        assert model.point_at(1.0) is None
        assert model.path_at(0.0) == []


class TestTimes:
    def test_times_follow_the_cumulative_time_index(self):
        ops = _mixed_ops()
        cumulative = ops.build_cumulative_time_index(*_params())

        model = JobPreviewModel.from_ops(ops, MACHINE)

        for segment in model.segments:
            assert segment.t1 == cumulative[segment.op_index]
            assert segment.t0 == cumulative[segment.op_index - 1]

    def test_times_are_monotonic_and_end_at_the_estimate(self):
        ops = _mixed_ops()

        model = JobPreviewModel.from_ops(ops, MACHINE)

        times = [t for s in model.segments for t in (s.t0, s.t1)]
        assert times == sorted(times)
        assert model.total_time == ops.estimate_time(*_params())

    def test_a_dwell_is_a_wait_between_segments(self):
        model = JobPreviewModel.from_ops(_mixed_ops(), MACHINE)
        arc, after = model.segments[2], model.segments[3]

        assert after.t0 - arc.t1 == pytest.approx(0.5)
        # The head waits at the end of the arc.
        middle = (arc.t1 + after.t0) / 2
        assert model.index_at(middle) == 3
        assert model.point_at(middle) == after.points[0]

    def test_a_matching_estimate_changes_nothing(self):
        ops = _mixed_ops()
        own = JobPreviewModel.from_ops(ops, MACHINE)
        estimate = own.total_time * (1 + ESTIMATE_TOLERANCE / 2)

        model = JobPreviewModel.from_ops(ops, MACHINE, estimate)

        assert model.total_time == own.total_time
        assert [s.t1 for s in model.segments] == [s.t1 for s in own.segments]

    def test_a_different_estimate_scales_every_time_onto_it(self):
        ops = _mixed_ops()
        own = JobPreviewModel.from_ops(ops, MACHINE)
        estimate = own.total_time * 2

        model = JobPreviewModel.from_ops(ops, MACHINE, estimate)

        assert model.total_time == pytest.approx(estimate)
        for scaled, base in zip(model.segments, own.segments):
            assert scaled.t0 == pytest.approx(base.t0 * 2)
            assert scaled.t1 == pytest.approx(base.t1 * 2)
        times = [t for s in model.segments for t in (s.t0, s.t1)]
        assert times == sorted(times)


class TestScrubbing:
    @pytest.fixture
    def model(self):
        ops = Ops()
        ops.set_power(1.0)
        ops.move_to(0.0, 0.0)
        ops.line_to(10.0, 0.0)
        ops.line_to(10.0, 10.0)
        return JobPreviewModel.from_ops(ops, MACHINE)

    def test_at_zero_nothing_is_finished(self, model):
        # The first move is from the origin to the origin: no time.
        assert model.segments[0].t1 == 0.0
        assert model.index_at(0.0) == 1
        assert model.path_at(0.0) == [(0.0, 0.0)]
        assert model.point_at(0.0) == (0.0, 0.0)

    def test_mid_segment(self, model):
        first = model.segments[1]
        middle = (first.t0 + first.t1) / 2

        assert model.index_at(middle) == 1
        assert model.point_at(middle) == pytest.approx((5.0, 0.0))
        path = model.path_at(middle)
        assert path[0] == (0.0, 0.0)
        assert path[-1] == pytest.approx((5.0, 0.0))

    def test_at_a_segment_boundary(self, model):
        assert model.index_at(model.segments[1].t1) == 2
        assert model.point_at(model.segments[1].t1) == (10.0, 0.0)

    def test_at_the_total_and_beyond(self, model):
        for t in (model.total_time, model.total_time + 10.0):
            assert model.index_at(t) == len(model.segments)
            assert model.path_at(t) == []
            assert model.point_at(t) == (10.0, 10.0)

    def test_before_the_start(self, model):
        assert model.index_at(-1.0) == 0
        assert model.point_at(-1.0) == (0.0, 0.0)

    def test_scrubbing_back_unfinishes_segments(self, model):
        assert model.index_at(model.total_time) == 3
        assert model.index_at(model.segments[1].t1 / 2) == 1


# --- The real job --------------------------------------------------------

SVG_DATA = b"""
<svg width="50mm" height="30mm" xmlns="http://www.w3.org/2000/svg">
<rect width="50" height="30" fill="#000000" />
</svg>"""


@pytest.fixture(autouse=True)
def _zero_debounce(zero_debounce_delay):
    """Rebuild on the next main-loop turn instead of 200 ms later."""


def _add_workpiece(doc: Doc, layer: Layer, pos: tuple[float, float]):
    workpiece = WorkPiece(name="rect.svg")
    source = SourceAsset(
        Path(workpiece.name),
        original_data=SVG_DATA,
        renderer=SVG_RENDERER,
    )
    doc.add_asset(source)
    workpiece.source_segment = SourceAssetSegment(
        source_asset_uid=source.uid,
        pristine_geometry=Geometry(),
        vectorization_spec=PassthroughSpec(),
    )
    workpiece.set_size(50, 30)
    workpiece.pos = pos
    layer.add_workpiece(workpiece)


def _two_layer_doc(context, engrave_cls, contour_cls) -> Doc:
    """
    Layer one: an engrave (raster) and a cut over one rectangle.
    Layer two: a cut over another. Layer three is hidden.
    """
    doc = Doc()
    first = doc.active_layer
    assert first.workflow is not None
    first.workflow.set_steps([])
    _add_workpiece(doc, first, (10.0, 20.0))
    first.workflow.add_step(engrave_cls.create(context, name="engrave"))
    first.workflow.add_step(contour_cls.create(context, name="cut"))

    for name, pos, visible in (
        ("second", (80.0, 60.0), True),
        ("hidden", (20.0, 90.0), False),
    ):
        layer = Layer(name=name)
        doc.add_child(layer)
        assert layer.workflow is not None
        _add_workpiece(doc, layer, pos)
        layer.workflow.add_step(contour_cls.create(context, name=name))
        layer.visible = visible
    return doc


@pytest_asyncio.fixture
async def job(
    task_mgr,
    context_initializer,
    test_machine_and_config,
    engrave_step_class,
    contour_step_class,
):
    """A real two-layer job on its pipeline, generated like a Start."""
    machine, _config = test_machine_and_config
    machine.driver_name = "RuidaDriver"
    machine.dialect_uid = None
    machine.hydrate()
    doc = _two_layer_doc(
        context_initializer, engrave_step_class, contour_step_class
    )
    pipeline = Pipeline(
        doc, task_mgr, context_initializer.artifact_store, machine
    )

    yield pipeline, doc, machine

    await asyncio.to_thread(task_mgr.wait_until_settled, 5000)
    pipeline.shutdown()


async def _preview(pipeline) -> tuple[JobPreviewModel, Ops, float]:
    """The preview, from the handle and checkout a Start uses."""
    handle = await asyncio.wait_for(
        pipeline.generate_job_artifact_async(), timeout=30
    )
    with pipeline.artifact_store.checkout_handle(handle) as artifact:
        assert isinstance(artifact, JobArtifact)
        model = JobPreviewModel.from_ops(
            artifact.ops, pipeline.machine, artifact.time_estimate
        )
        return model, artifact.ops.copy(), artifact.time_estimate


class TestTheRealJob:
    @pytest.mark.asyncio
    async def test_preview_order_is_the_job_op_order(self, job):
        pipeline, _doc, _machine = job

        model, ops, _estimate = await _preview(pipeline)

        moving = _moving(ops)
        assert [s.op_index for s in model.segments] == moving
        for segment in model.segments:
            command = ops.command_type(segment.op_index)
            assert segment.points[-1] == pytest.approx(
                ops.endpoint(segment.op_index)[:2]
            ), command
        kinds = {s.kind for s in model.segments}
        assert kinds == {TRAVEL, CUT, SCAN}
        assert all(
            s.kind == SCAN
            for s in model.segments
            if ops.command_type(s.op_index) == CommandType.SCAN_LINE
        )

    @pytest.mark.asyncio
    async def test_the_preview_total_is_the_estimate_unscaled(self, job):
        """On a real job the two clocks agree: nothing is scaled."""
        pipeline, _doc, machine = job

        model, ops, estimate = await _preview(pipeline)

        assert estimate > 0
        assert (
            model.total_time
            == ops.build_cumulative_time_index(*_params(machine))[-1]
        )
        assert model.total_time == pytest.approx(estimate, rel=1e-9)

    @pytest.mark.asyncio
    async def test_a_send_hands_the_driver_the_previewed_ops(
        self, job, task_mgr
    ):
        pipeline, doc, machine = job
        model, previewed, _estimate = await _preview(pipeline)

        class Driver:
            native_overscan = False
            ops = None

            async def run(self, encoded, doc, ops, on_command_done=None):
                Driver.ops = ops.copy()

        editor = MagicMock()
        editor.pipeline = pipeline
        editor.doc = doc
        editor.task_manager = task_mgr
        with patch.object(
            type(machine),
            "driver",
            new_callable=PropertyMock,
            return_value=Driver(),
        ):
            await MachineCmd(editor).send_job(machine)

        assert Driver.ops is not None
        assert Driver.ops.to_dict() == previewed.to_dict()
        assert [s.op_index for s in model.segments] == _moving(Driver.ops)
