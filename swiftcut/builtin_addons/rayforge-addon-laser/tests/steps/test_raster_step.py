import io
from typing import cast
from unittest.mock import MagicMock, Mock, patch

import cairo
import numpy as np
import pytest
from laser_essentials.steps import EngraveStep, raster_step
from raygeo.cnc.execution.specs import ComputePayload
from raygeo.geo import Geometry, Matrix
from raygeo.ops.assembly import Assembler
from raygeo.ops.assembly.raster import RasterSpec
from raygeo.ops.part import Part

from swiftcut.core.step_registry import step_registry
from swiftcut.core.vectorization_spec import TraceSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.image.ops_renderer import OPS_RENDERER
from swiftcut.image.png.importer import PngImporter
from swiftcut.image.util.grayscale import surface_to_grayscale
from swiftcut.pipeline.stage.assembler_helpers import (
    DepthMode,
    compute_raster_auto_levels,
    preprocess_raster_image,
)


@pytest.fixture
def mock_context():
    context = MagicMock()
    machine = MagicMock()
    machine.max_cut_speed = 5000
    machine.max_travel_speed = 10000
    machine.acceleration = 3000
    default_head = MagicMock()
    default_head.uid = "test-laser-uid"
    default_head.spot_size_mm = (0.1, 0.1)
    machine.get_default_laser_head.return_value = default_head
    context.machine = machine
    return context


class TestEngraveStep:
    def test_instantiation(self):
        step = EngraveStep(name="Test")
        assert step.typelabel == "Engrave"

    def test_create(self, mock_context):
        step = EngraveStep.create(mock_context, name="Created")
        assert isinstance(step, EngraveStep)
        assert len(step.per_workpiece_transformers_dicts) == 3
        transformer_names = {
            t.get("name") for t in step.per_workpiece_transformers_dicts
        }
        assert "BidirScanOffsetTransformer" in transformer_names
        assert step.selected_head_uid == "test-laser-uid"

    def test_serialization_includes_step_type(self):
        step = EngraveStep(name="Test")
        data = step.to_dict()
        assert data["step_type"] == "EngraveStep"

    def test_registry_create_engrave_step(self, mock_context):
        StepClass = step_registry.get("EngraveStep")
        assert StepClass is not None
        step = StepClass.create(mock_context, name="FromRegistry")
        assert type(step).__name__ == "EngraveStep"

    def test_get_assembler_kwargs(self, machine):
        step = EngraveStep(name="Test")
        workpiece = MagicMock(spec=["size"])
        workpiece.size = (100, 100)
        kwargs = step.get_assembler_kwargs(machine, workpiece)
        assert isinstance(kwargs, dict)
        expected_keys = {
            "mode",
            "line_interval_mm",
            "sample_interval_mm",
            "dot_width_correction_mm",
            "min_power",
            "max_power",
            "step_power",
            "num_power_levels",
            "angle",
            "offset_x_mm",
            "offset_y_mm",
            "scan_mode",
            "cross_hatch",
            "num_depth_levels",
            "z_step_down",
            "angle_increment",
            "engrave_mode",
            "stroke_width_mm",
        }
        assert set(kwargs.keys()) == expected_keys

    def test_roundtrip_serialization(self):
        step = EngraveStep(name="Test")
        step.scan_angle = 45.0
        step.depth_mode = "MULTI_PASS"
        step.line_interval_mm = 0.2  # type: ignore[assignment]
        step.dot_width_correction_mm = 0.05  # type: ignore[assignment]
        data = step.to_dict()
        restored = EngraveStep.from_dict(data)
        assert data == restored.to_dict()
        assert restored.dot_width_correction_mm == 0.05

    def test_engrave_mode_defaults_to_both(self):
        assert EngraveStep(name="Test").engrave_mode == "BOTH"

    def test_engrave_mode_roundtrips(self):
        step = EngraveStep(name="Test")
        step.engrave_mode = "OUTLINE"
        restored = EngraveStep.from_dict(step.to_dict())
        assert restored.engrave_mode == "OUTLINE"
        assert "engrave_mode" not in restored.extra

    @pytest.mark.parametrize("saved", [None, "STROKE"])
    def test_missing_or_unknown_engrave_mode_loads_as_both(self, saved):
        """Files written before the option existed (or with a value
        this build does not know) engrave vector shapes as Both."""
        data = EngraveStep(name="Test").to_dict()
        if saved is None:
            del data["engrave_mode"]
        else:
            data["engrave_mode"] = saved
        assert EngraveStep.from_dict(data).engrave_mode == "BOTH"

    @pytest.mark.parametrize(
        "spot, width",
        [((0.1, 0.1), 0.2), ((0.3, 0.25), 0.3), ((0.15, 0.35), 0.35)],
    )
    def test_stroke_width_is_spot_size_or_minimum(self, machine, spot, width):
        machine.heads[0].spot_size_mm = spot
        step = EngraveStep(name="Test")
        kwargs = step.get_assembler_kwargs(machine, MagicMock())
        assert kwargs["stroke_width_mm"] == width

    def test_legacy_power_keys_migrate(self):
        """Old files keyed the raster power range as min_power/max_power.

        Those must load into min_power_level/max_power_level and must not
        pollute extra. The hardware max_power slot is restored to its
        default rather than inheriting the old raster ceiling.
        """
        step = EngraveStep(name="Test")
        data = step.to_dict()
        data["min_power"] = data.pop("min_power_level")
        data["max_power"] = data.pop("max_power_level")
        data["min_power"] = 0.2
        data["max_power"] = 1.0

        restored = EngraveStep.from_dict(data)

        assert restored.min_power_level == 0.2
        assert restored.max_power_level == 1.0
        assert restored.max_power == 1000
        assert "min_power" not in restored.extra
        assert "max_power" not in restored.extra

    def test_from_dict_migrates_legacy_opsproducer_params(self):
        """True legacy files store raster params in
        ``opsproducer_dict.params``; loading must restore them."""
        step = EngraveStep(name="Test")
        data = step.to_dict()
        for key in (
            "scan_angle",
            "depth_mode",
            "invert",
            "auto_levels",
            "black_point",
            "white_point",
            "threshold",
            "line_interval_mm",
            "sample_interval_mm",
            "min_power_level",
            "max_power_level",
            "num_power_levels",
            "scan_mode",
            "cross_hatch",
            "num_depth_levels",
            "z_step_down",
            "angle_increment",
            "dither_algorithm",
        ):
            data.pop(key, None)
        data["opsproducer_dict"] = {
            "type": "Rasterizer",
            "params": {
                "direction_degrees": 45.0,
                "scan_mode": "FullSweep",
                "threshold": 100,
                "dither_algorithm": "bayer4",
                "cross_hatch": True,
                "min_power": 0.2,
                "max_power": 0.9,
                "num_depth_levels": 3,
                "num_power_levels": 10,
                "z_step_down": 0.5,
                "invert": True,
                "auto_levels": False,
                "black_point": 20,
                "white_point": 200,
                "angle_increment": 30.0,
                "line_interval_mm": 0.4,
            },
        }

        restored = EngraveStep.from_dict(data)

        assert restored.depth_mode == "CONSTANT_POWER"
        assert restored.scan_angle == 45.0
        assert restored.scan_mode == "FULL_SWEEP"
        assert restored.threshold == 100
        assert restored.dither_algorithm is not None
        assert restored.dither_algorithm.name == "BAYER4"
        assert restored.cross_hatch is True
        assert restored.min_power_level == 0.2
        assert restored.max_power_level == 0.9
        assert restored.num_depth_levels == 3
        assert restored.num_power_levels == 10
        assert restored.z_step_down == 0.5
        assert restored.invert is True
        assert restored.auto_levels is False
        assert restored.black_point == 20
        assert restored.white_point == 200
        assert restored.angle_increment == 30.0
        assert restored.line_interval_mm == 0.4
        assert restored.max_power == 1000

    def test_from_dict_dither_rasterizer_uses_dither_mode(self):
        """The legacy ``DitherRasterizer`` type implies DITHER mode."""
        step = EngraveStep(name="Test")
        data = step.to_dict()
        for key in ("depth_mode", "scan_angle", "threshold"):
            data.pop(key, None)
        data["opsproducer_dict"] = {
            "type": "DitherRasterizer",
            "params": {"threshold": 150},
        }

        restored = EngraveStep.from_dict(data)

        assert restored.depth_mode == "DITHER"
        assert restored.threshold == 150


class TestEngraveComputePayload:
    """Verifies EngraveStep's build_compute_payload (B3)."""

    def test_build_compute_payload_returns_raster_spec(self, machine):
        step = EngraveStep(name="engrave")
        step.min_power_level = 0.1
        step.max_power_level = 0.9
        wp = WorkPiece(name="wp")
        wp.set_size(10.0, 10.0)

        with patch.object(WorkPiece, "render_to_pixels", return_value=None):
            part, payload = step.build_compute_payload(machine, wp)

        assert isinstance(part, Part)
        assert isinstance(payload, ComputePayload)
        assert isinstance(payload.assembler, Assembler)
        spec = payload.assembler.spec
        assert isinstance(spec, RasterSpec)
        assert spec.min_power == 0.1
        assert spec.max_power == 0.9
        assert spec.mode == "power_modulated"

    def test_assembler_token_params_mirrors_kwargs(self, machine):
        step = EngraveStep(name="engrave")
        wp = WorkPiece(name="wp")
        wp.set_size(10.0, 10.0)
        token = step.assembler_token_params(machine, wp)
        kwargs = step.get_assembler_kwargs(machine, wp)
        assert token == kwargs


# --- Vector shapes: Engrave Fill / Outline / Both ---------------------
#
# The lab machines have a 0.1 mm spot, so the raster grid is 20 px/mm
# across (half-spot samples) and 10 px/mm down (one row per line).
PX_X, PX_Y = 20, 10


def _hairline_render(self, width, height):
    """Today's base render of a DXF / Ruida / LightBurn line shape:
    the shared ops renderer strokes it as a 1.5 px hairline."""
    return OPS_RENDERER._render_to_cairo_surface(
        self.boundaries, width, height
    )


def _vector_workpiece(geometry, size=(20.0, 10.0)):
    wp = WorkPiece(name="shape")
    wp._edited_boundaries = geometry
    wp.set_size(*size)
    # The base renderer maps the geometry's rect onto the image and the
    # ink maps the unit box, so the two coincide only for normalized
    # geometry, which is what WorkPiece.boundaries holds.
    assert geometry.rect() == pytest.approx((0.0, 0.0, 1.0, 1.0))
    return wp


def _line_shape():
    """A line-only drawing with a real bounding box (20 x 10 mm): a
    rectangle outline, a horizontal line across its middle and a
    diagonal."""
    geo = Geometry()
    geo.move_to(0, 0)
    geo.line_to(1, 0)
    geo.line_to(1, 1)
    geo.line_to(0, 1)
    geo.close_path()
    geo.move_to(0.1, 0.5)
    geo.line_to(0.9, 0.5)
    geo.move_to(0.1, 0.1)
    geo.line_to(0.9, 0.9)
    return geo


def _circle(geo, radius):
    """Append a closed circle centred in the unit box."""
    geo.move_to(0.5 + radius, 0.5)
    geo.arc_to(0.5 - radius, 0.5, -radius, 0.0, False)
    geo.arc_to(0.5 + radius, 0.5, radius, 0.0, False)
    return geo


def _raster_input(step, machine, wp, render=_hairline_render):
    """Run the raster producer and capture the surface it hands to
    preprocessing. Returns (alpha array, preprocess kwargs, part,
    alpha returned with the part)."""
    seen = {}
    real = raster_step.preprocess_raster_image

    def spy(surface, **kwargs):
        seen["alpha"] = surface_to_grayscale(surface)[1].copy()
        seen["kwargs"] = kwargs
        return real(surface, **kwargs)

    with (
        patch.object(WorkPiece, "render_to_pixels", render),
        patch.object(raster_step, "preprocess_raster_image", spy),
    ):
        part, alpha = raster_step._build_raster_part(step, machine, wp)
    return seen["alpha"], seen["kwargs"], part, alpha


def _engrave(mode):
    step = EngraveStep(name="engrave")
    step.engrave_mode = mode
    return step


def _col(x_mm):
    return int(x_mm * PX_X)


def _row(y_mm, height_mm):
    """Image row holding the band just below ``y_mm`` (Y-up)."""
    return round((height_mm - y_mm) * PX_Y)


class TestEngraveVectorShapes:
    def test_line_shape_engraves_unbroken_lines(self, machine):
        """A 0.1 mm line drawing must reach the raster as solid lines,
        not as the faint hairline the base render draws."""
        wp = _vector_workpiece(_line_shape())
        base = surface_to_grayscale(_hairline_render(wp, 400, 100))[1]
        alpha, _kw, _part, _a = _raster_input(_engrave("OUTLINE"), machine, wp)
        assert alpha.shape == (100, 400)
        full = 0.99

        # The middle line (y = 5 mm, x 2..18 mm) fills both rows of
        # its 0.2 mm band along its whole length. The hairline alone
        # stays faint there (left of where the diagonal crosses).
        rows = slice(_row(5.1, 10), _row(4.9, 10))
        assert base[rows, 44:180].max() < 0.5
        assert alpha[rows, 44:356].min() >= full

        # Every edge of the outline, including the vertical ones on the
        # bounding box, is fully inked 0.2 mm into the shape (the
        # outer corners are rounded by the round line join).
        assert alpha[0:2, 4:396].min() >= full
        assert alpha[98:100, 4:396].min() >= full
        assert alpha[2:98, 0:4].min() >= full
        assert alpha[2:98, 396:400].min() >= full

        # The diagonal (2, 1) -> (18, 9) mm: every column and every row
        # it crosses has a fully inked pixel next to the line.
        for col in range(_col(2.4), _col(17.6)):
            y = 1.0 + ((col + 0.5) / PX_X - 2.0) / 2.0
            r = _row(y, 10)
            assert alpha[r - 3 : r + 3, col].max() >= full, col
        for row in range(_row(8.6, 10), _row(1.4, 10)):
            x = 2.0 + (10.0 - (row + 0.5) / PX_Y - 1.0) * 2.0
            c = _col(x)
            assert alpha[row, c - 8 : c + 8].max() >= full, row

    @pytest.mark.parametrize("mode", ["FILL", "BOTH"])
    def test_closed_circle_fills(self, machine, mode):
        wp = _vector_workpiece(_circle(Geometry(), 0.5), (10.0, 10.0))
        alpha, *_ = _raster_input(_engrave(mode), machine, wp)
        assert alpha.shape == (100, 200)
        assert alpha[45:55, 90:110].min() >= 0.99
        # The fill reaches the bounding box at the circle's widest row.
        assert alpha[49:51, 0:2].min() >= 0.99

    def test_closed_circle_outline_is_a_ring(self, machine):
        wp = _vector_workpiece(_circle(Geometry(), 0.5), (10.0, 10.0))
        alpha, *_ = _raster_input(_engrave("OUTLINE"), machine, wp)
        assert alpha[45:55, 90:110].max() == 0.0
        # A 0.2 mm band (4 columns) on the left, then the open middle.
        assert alpha[49:51, 0:4].min() >= 0.99
        assert alpha[49:51, 8:190].max() == 0.0

    def test_fill_leaves_holes_open(self, machine):
        """Even-odd: a closed shape inside another is a hole."""
        geo = _circle(_circle(Geometry(), 0.5), 0.25)
        wp = _vector_workpiece(geo, (10.0, 10.0))
        alpha, *_ = _raster_input(_engrave("FILL"), machine, wp)
        assert alpha[45:55, 90:110].max() == 0.0
        assert alpha[49:51, 20:40].min() >= 0.99

    def test_fill_adds_nothing_to_open_paths(self, machine):
        geo = Geometry()
        geo.move_to(0, 0)
        geo.line_to(1, 1)
        wp = _vector_workpiece(geo)
        base = surface_to_grayscale(_hairline_render(wp, 400, 100))[1]
        alpha, *_ = _raster_input(_engrave("FILL"), machine, wp)
        assert np.array_equal(alpha, base)

    def test_ink_keeps_antialiased_edges(self, machine):
        """Power modulation with auto levels must keep the stroke's
        edge coverage as intermediate power, not stretch it into hard
        steps (or fail on a near-flat histogram)."""
        geo = Geometry()
        geo.move_to(0, 0)
        geo.line_to(1, 1)
        wp = _vector_workpiece(geo)
        step = _engrave("OUTLINE")
        assert step.depth_mode == "POWER_MODULATION"
        assert step.auto_levels is True
        _alpha, kwargs, part, _a = _raster_input(step, machine, wp)
        assert kwargs["computed_auto_levels"] == (0, 255)
        assert part.image_source is not None
        image = np.frombuffer(part.image_source.read_all(), np.uint8)
        assert image.min() == 0
        assert ((image > 0) & (image < 255)).any()

    def test_shape_without_a_base_render_still_engraves(self, machine):
        wp = _vector_workpiece(_line_shape())
        alpha, _kw, part, _a = _raster_input(
            _engrave("OUTLINE"),
            machine,
            wp,
            render=lambda self, w, h: None,
        )
        assert part.image_source is not None
        assert alpha[2:98, 0:4].min() >= 0.99


def _traced_bitmap_workpiece():
    """A PNG imported the photo way (TraceSpec): a gray gradient block
    on white. Its trace is a closed rectangle, so it is the case that
    must not get vector ink."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 80)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    gradient = cairo.LinearGradient(20, 0, 100, 0)
    gradient.add_color_stop_rgb(0, 0.1, 0.1, 0.1)
    gradient.add_color_stop_rgb(1, 0.7, 0.7, 0.7)
    ctx.set_source(gradient)
    ctx.rectangle(20, 20, 80, 40)
    ctx.fill()
    buf = io.BytesIO()
    surface.write_to_png(buf)

    result = PngImporter(buf.getvalue()).get_doc_items(
        vectorization_spec=TraceSpec()
    )
    assert result is not None and result.payload is not None
    source = result.payload.source
    wp = cast(WorkPiece, result.payload.items[0])
    doc = Mock()
    doc.source_assets = {source.uid: source}
    doc.get_source_asset_by_uid.side_effect = doc.source_assets.get
    parent = Mock()
    parent.doc = doc
    parent.get_world_transform.return_value = Matrix.identity()
    wp.parent = parent
    assert wp.boundaries is not None and not wp.boundaries.is_empty()
    return wp


class TestEngraveTracedBitmap:
    def test_traced_bitmap_raster_is_unchanged(self, machine):
        """A traced bitmap keeps today's raster byte for byte: its own
        render, levels from the preview render, no vector ink, in every
        Engrave mode."""
        wp = _traced_bitmap_workpiece()
        step = EngraveStep(name="engrave")
        w = int(wp.size[0] * PX_X)
        h = int(wp.size[1] * PX_Y)
        ppm = (w / wp.size[0], h / wp.size[1])
        expected, expected_alpha = preprocess_raster_image(
            wp.render_to_pixels(w, h),
            mode=DepthMode[step.depth_mode],
            auto_levels=True,
            computed_auto_levels=compute_raster_auto_levels(wp, ppm),
            laser_spot_x_mm=0.1,
            pixels_per_mm_x=ppm[0],
        )
        assert expected is not None and expected_alpha is not None
        assert ((expected > 0) & (expected < 255)).any()

        for mode in ("FILL", "OUTLINE", "BOTH"):
            step.engrave_mode = mode
            part, alpha = raster_step._build_raster_part(step, machine, wp)
            assert part.pixels_per_mm == pytest.approx(ppm)
            assert part.image_source is not None
            assert part.image_source.read_all() == expected.tobytes(), mode
            assert alpha is not None
            assert np.array_equal(alpha, expected_alpha), mode
