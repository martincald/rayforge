import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from raygeo.geo import Matrix
from raygeo.ops.state import CoolantMode

from swiftcut.core.bed_bounds import inside
from swiftcut.core.doc import Doc
from swiftcut.core.group import Group
from swiftcut.core.layer import Layer
from swiftcut.core.source_asset import SourceAsset
from swiftcut.core.step import Step
from swiftcut.core.stock_asset import StockAsset
from swiftcut.core.vectorization_spec import PassthroughSpec, TraceSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.doceditor.file_cmd import (
    FileCmd,
    ImportAction,
    PreviewResult,
    _unsupported_coolant_labels,
)
from swiftcut.doceditor.layout.outline import item_world_polygons
from swiftcut.image import (
    ImporterFeature,
    ImportManifest,
    ImportPayload,
    ImportResult,
    LayerInfo,
    ParsingResult,
)
from swiftcut.image.dxf.importer import DxfImporter
from swiftcut.image.lightburn.importer import LightBurnImporter
from swiftcut.image.ruida.importer import RuidaImporter
from swiftcut.image.svg.importer import SvgImporter
from swiftcut.image.svg.renderer import SVG_RENDERER
from swiftcut.machine.models.coordspace import (
    AxisDirection,
    MachineSpace,
    OriginCorner,
)
from swiftcut.machine.models.machine import Machine
from swiftcut.machine.models.spindle import SpindleHead
from swiftcut.shared.placement import engine
from swiftcut.shared.tasker.manager import TaskManager

TESTS_DIR = Path(__file__).parent.parent
LARGE_DXF = TESTS_DIR / "perf" / "large.dxf"
SWITCH_PLATE = (
    TESTS_DIR / "image" / "lightburn" / "assets" / "switch_plate.lbrn2"
)


@pytest.fixture
def mock_editor(context_initializer):
    """Provides a DocEditor instance with mocked dependencies."""
    task_manager = MagicMock(spec=TaskManager)
    doc = Doc()
    editor = DocEditor(task_manager, context_initializer, doc)
    yield editor
    editor.cleanup()


@pytest.fixture
def file_cmd(mock_editor):
    """Provides a FileCmd instance."""
    return FileCmd(mock_editor, mock_editor.task_manager)


def _doc_with_mill_step():
    """A doc whose active layer workflow holds one mill step."""
    doc = Doc()
    workflow = doc.active_layer.workflow
    step = Step(typelabel="Mill", name="Mill Step")
    assert workflow is not None
    workflow.add_child(step)
    return doc, step


def _spindle_machine(context, cooling_methods):
    """A machine with a single spindle head supporting the given methods."""
    machine = Machine(context)
    machine.heads.clear()
    head = SpindleHead()
    head.cooling_methods = tuple(cooling_methods)
    machine.add_head(head)
    return machine


def test_unsupported_coolant_labels_without_machine(context_initializer):
    doc, step = _doc_with_mill_step()
    step.set_coolant_method(CoolantMode.MIST)
    assert _unsupported_coolant_labels(doc, None) == []


def test_unsupported_coolant_labels_supported_method(context_initializer):
    doc, step = _doc_with_mill_step()
    machine = _spindle_machine(context_initializer, [CoolantMode.FLOOD])
    step.set_coolant_method(CoolantMode.FLOOD)
    assert _unsupported_coolant_labels(doc, machine) == []


def test_unsupported_coolant_labels_reports_missing_method(
    context_initializer,
):
    doc, step = _doc_with_mill_step()
    machine = _spindle_machine(context_initializer, [CoolantMode.FLOOD])
    step.set_coolant_method(CoolantMode.MIST)
    assert _unsupported_coolant_labels(doc, machine) == ["Mist"]


def test_unsupported_coolant_labels_dedupes(context_initializer):
    doc, step = _doc_with_mill_step()
    step2 = Step(typelabel="Mill", name="Second Mill")
    workflow = doc.active_layer.workflow
    assert workflow is not None
    workflow.add_child(step2)
    machine = _spindle_machine(context_initializer, [])
    step.set_coolant_method(CoolantMode.FLOOD)
    step2.set_coolant_method(CoolantMode.MIST)
    assert _unsupported_coolant_labels(doc, machine) == ["Flood", "Mist"]


@pytest.fixture
def sample_workpiece():
    """Provides a sample WorkPiece instance."""
    wp = WorkPiece(name="Test WorkPiece")
    wp.set_size(10.0, 20.0)
    return wp


@pytest.fixture
def sample_layer():
    """Provides a sample Layer instance."""
    return Layer(name="Test Layer")


@pytest.fixture
def sample_source_asset():
    """Provides a sample SourceAsset instance."""
    asset = SourceAsset(
        source_file=Path("test.svg"),
        original_data=b"<svg></svg>",
        renderer=SVG_RENDERER,
    )
    return asset


@pytest.fixture
def sample_payload(sample_workpiece, sample_source_asset):
    """Provides a sample ImportPayload instance."""
    return ImportPayload(
        source=sample_source_asset,
        items=[sample_workpiece],
    )


@pytest.fixture
def sample_parse_result():
    """Provides a sample ParsingResult."""
    document_bounds = (0, 0, 10, 10)
    unit_scale = 1.0
    x, _y, w, h = document_bounds
    world_frame = (x * unit_scale, 0.0, w * unit_scale, h * unit_scale)
    return ParsingResult(
        document_bounds=document_bounds,
        native_unit_to_mm=unit_scale,
        is_y_down=True,
        layers=[],
        world_frame_of_reference=world_frame,
        background_world_transform=Matrix.identity(),
    )


@pytest.fixture
def sample_import_result(sample_payload, sample_parse_result):
    """Provides a sample ImportResult."""
    return ImportResult(
        payload=sample_payload, parse_result=sample_parse_result
    )


class TestScanImportFile:
    """Tests for scan_import_file method."""

    def test_scan_delegates_to_importer(self, file_cmd):
        """
        Test that scan_import_file correctly finds and calls the
        importer's scan method.
        """
        svg_bytes = b"<svg></svg>"
        file_path = Path("test.svg")
        mime_type = "image/svg+xml"

        mock_importer_instance = MagicMock()
        mock_manifest = ImportManifest(
            layers=[LayerInfo(id="layer1", name="Layer 1")]
        )
        mock_importer_instance.scan.return_value = mock_manifest

        mock_importer_class = MagicMock()
        mock_importer_class.return_value = mock_importer_instance

        with patch(
            "swiftcut.doceditor.file_cmd.importer_registry.get_by_extension",
            return_value=mock_importer_class,
        ):
            result = file_cmd.scan_import_file(svg_bytes, file_path, mime_type)

            mock_importer_class.assert_called_once_with(
                data=svg_bytes, source_file=file_path
            )
            mock_importer_instance.scan.assert_called_once()
            assert result is mock_manifest

    def test_scan_no_importer_found(self, file_cmd, caplog):
        """Test scanning a file with no matching importer."""
        some_bytes = b"data"
        file_path = Path("test.unknown")
        mime_type = "application/octet-stream"

        with (
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry."
                "get_by_mime_type",
                return_value=None,
            ),
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry"
                ".get_by_extension",
                return_value=None,
            ),
        ):
            result = file_cmd.scan_import_file(
                some_bytes, file_path, mime_type
            )

            assert isinstance(result, ImportManifest)
            assert result.title == "test.unknown"
            assert result.warnings == ["Unsupported file type: .unknown"]
            assert "No importer found" in caplog.text

    def test_scan_importer_raises_exception(self, file_cmd, caplog):
        """
        Test that exceptions during the importer's scan are handled
        gracefully.
        """
        svg_bytes = b"<svg></svg>"
        file_path = Path("test.svg")
        mime_type = "image/svg+xml"

        mock_importer_instance = MagicMock()
        mock_importer_instance.scan.side_effect = ValueError("Parsing failed")

        mock_importer_class = MagicMock()
        mock_importer_class.__name__ = "MockSvgImporter"
        mock_importer_class.return_value = mock_importer_instance

        with patch(
            "swiftcut.doceditor.file_cmd.importer_registry.get_by_extension",
            return_value=mock_importer_class,
        ):
            result = file_cmd.scan_import_file(svg_bytes, file_path, mime_type)

            assert isinstance(result, ImportManifest)
            assert result.title == "test.svg"
            assert result.warnings == [
                "An unexpected error occurred during file analysis."
            ]
            assert "Error scanning file" in caplog.text
            assert "MockSvgImporter" in caplog.text


class TestExtractFirstWorkpiece:
    """Tests for _extract_first_workpiece method."""

    def test_extract_workpiece_from_list(self, file_cmd, sample_workpiece):
        """Test extracting WorkPiece from a list of items."""
        result = file_cmd._extract_first_workpiece([sample_workpiece])

        assert result is sample_workpiece

    def test_extract_workpiece_from_layer(self, file_cmd, sample_workpiece):
        """Test extracting WorkPiece from a Layer's children."""
        layer = Layer(name="Test Layer")
        layer.add_child(sample_workpiece)

        result = file_cmd._extract_first_workpiece([layer])

        assert result is sample_workpiece

    def test_extract_workpiece_from_nested_layer(self, file_cmd):
        """Test extracting WorkPiece from nested Layers."""
        outer_layer = Layer(name="Outer Layer")
        inner_layer = Layer(name="Inner Layer")
        wp = WorkPiece(name="Nested WorkPiece")
        inner_layer.add_child(wp)
        outer_layer.add_child(inner_layer)

        result = file_cmd._extract_first_workpiece([outer_layer])

        assert result is wp

    def test_extract_workpiece_not_found(self, file_cmd, sample_layer):
        """Test returning None when no WorkPiece is found."""
        result = file_cmd._extract_first_workpiece([sample_layer])

        assert result is None

    def test_extract_workpiece_empty_list(self, file_cmd):
        """Test returning None for empty list."""
        result = file_cmd._extract_first_workpiece([])

        assert result is None


class TestCalculateItemsBbox:
    """Tests for _calculate_items_bbox method."""

    def test_calculate_bbox_single_item(self, file_cmd, sample_workpiece):
        """Test calculating bbox for a single item."""
        sample_workpiece.set_size(10.0, 20.0)
        sample_workpiece.pos = (5.0, 10.0)

        result = file_cmd._calculate_items_bbox([sample_workpiece])

        assert result is not None
        _x, _y, w, h = result
        assert w == 10.0
        assert h == 20.0

    def test_calculate_bbox_multiple_items(self, file_cmd):
        """Test calculating bbox for multiple items."""
        wp1 = WorkPiece(name="Item 1")
        wp1.set_size(10.0, 10.0)
        wp1.pos = (0.0, 0.0)

        wp2 = WorkPiece(name="Item 2")
        wp2.set_size(15.0, 15.0)
        wp2.pos = (10.0, 10.0)

        result = file_cmd._calculate_items_bbox([wp1, wp2])

        assert result is not None
        x, y, w, h = result
        assert x == 0.0
        assert y == 0.0
        assert w == 25.0
        assert h == 25.0

    def test_calculate_bbox_empty_list(self, file_cmd):
        """Test returning None for empty list."""
        result = file_cmd._calculate_items_bbox([])

        assert result is None


class TestPositionNewlyImportedItems:
    """Tests for _position_newly_imported_items method."""

    def test_position_at_specific_point(self, file_cmd, sample_workpiece):
        """Test positioning items at a specific point."""
        sample_workpiece.set_size(10.0, 20.0)
        sample_workpiece.pos = (0.0, 0.0)
        items = [sample_workpiece]

        file_cmd._position_newly_imported_items(items, (50.0, 100.0))

        assert pytest.approx(45.0) == sample_workpiece.pos[0]
        assert pytest.approx(90.0) == sample_workpiece.pos[1]

    def test_position_multiple_items_same_delta(self, file_cmd):
        """Test that multiple items get the same delta."""
        wp1 = WorkPiece(name="Item 1")
        wp1.set_size(10.0, 10.0)
        wp1.pos = (0.0, 0.0)

        wp2 = WorkPiece(name="Item 2")
        wp2.set_size(15.0, 15.0)
        wp2.pos = (10.0, 10.0)

        items = [wp1, wp2]
        file_cmd._position_newly_imported_items(items, (50.0, 50.0))

        assert pytest.approx(37.5) == wp1.pos[0]
        assert pytest.approx(37.5) == wp1.pos[1]
        assert pytest.approx(47.5) == wp2.pos[0]
        assert pytest.approx(47.5) == wp2.pos[1]

    def test_position_none_uses_fit_and_position(
        self, file_cmd, sample_workpiece
    ):
        """Test that None position places at the nearest free spot."""
        with patch.object(
            file_cmd, "_place_at_nearest_free_spot"
        ) as mock_place:
            file_cmd._position_newly_imported_items([sample_workpiece], None)

            mock_place.assert_called_once_with([sample_workpiece], None)


class TestFitAndPlaceAtNearestFreeSpot:
    """Tests for _place_at_nearest_free_spot method."""

    def test_fit_and_position_no_config(self, file_cmd, sample_workpiece):
        """Test that method returns early when no config is available."""
        with patch("swiftcut.doceditor.file_cmd.get_context") as mock_ctx:
            mock_ctx.return_value.config = None

            file_cmd._place_at_nearest_free_spot([sample_workpiece], None)

    def test_fit_and_position_no_machine(self, file_cmd, sample_workpiece):
        """Test that method returns early when no machine is configured."""
        with patch("swiftcut.doceditor.file_cmd.get_context") as mock_ctx:
            mock_ctx.return_value.config.machine = None

            file_cmd._place_at_nearest_free_spot([sample_workpiece], None)

    def test_fit_and_position_no_bbox(self, file_cmd, sample_workpiece):
        """Test that method returns early when bbox cannot be calculated."""
        with patch.object(
            file_cmd, "_calculate_items_bbox", return_value=None
        ):
            file_cmd._place_at_nearest_free_spot([sample_workpiece], None)

    def test_fit_and_position_scale_down(self, file_cmd):
        """
        Test scaling down items that are too large. Without an oversize
        policy (headless) it scales silently: there is no "Reset" toast
        that could restore a piece larger than the bed.
        """
        wp = WorkPiece(name="Large Item")
        wp.set_size(300.0, 200.0)
        wp.pos = (0.0, 0.0)
        notifications = []
        file_cmd._editor.notification_requested.connect(
            lambda sender, **kwargs: notifications.append(kwargs), weak=False
        )

        with patch("swiftcut.doceditor.file_cmd.get_context") as mock_ctx:
            mock_machine = MagicMock()
            mock_machine.axis_extents = (200, 150)
            mock_machine.work_area = (0, 0, 200, 150)
            mock_machine.panel.reference_position_world = (0, 0)
            mock_machine.panel.world_position_from_origin.return_value = (
                0,
                0,
            )
            mock_machine.get_coordinate_space.return_value = MachineSpace(
                origin=OriginCorner.BOTTOM_LEFT,
                x_positive_direction=AxisDirection.POSITIVE_RIGHT,
                y_positive_direction=AxisDirection.POSITIVE_UP,
                extents=(200, 150),
            )
            mock_ctx.return_value.config.machine = mock_machine

            file_cmd._position_newly_imported_items([wp], None)

            bbox = wp.bbox
            assert bbox[2] <= 200
            assert bbox[3] <= 150
            assert notifications == []

    def test_fit_and_position_at_bed_centre(self, file_cmd):
        """Test positioning items at the centre of an empty bed."""
        wp = WorkPiece(name="Item")
        wp.set_size(50.0, 50.0)
        wp.pos = (0.0, 0.0)

        with patch("swiftcut.doceditor.file_cmd.get_context") as mock_ctx:
            mock_machine = MagicMock()
            mock_machine.axis_extents = (200, 150)
            mock_ctx.return_value.config.machine = mock_machine

            file_cmd._position_newly_imported_items([wp], None)

            bbox = wp.bbox
            # Item should be centred on the 200 x 150 bed
            assert abs(bbox[0] - 75) < 1e-6
            assert abs(bbox[1] - 50) < 1e-6

    def test_large_dxf_beside_a_copy_tests_only_near_outlines(
        self, file_cmd, monkeypatch
    ):
        """
        large.dxf has 500 outlines. Placed beside a copy of itself, it
        gets the exact test only for pairs of outlines whose boxes
        overlap: testing every pair took over 200,000 exact tests and
        seconds on the main thread.
        """
        exact_tests = []
        real = engine.do_polygons_intersect
        monkeypatch.setattr(
            engine,
            "do_polygons_intersect",
            lambda a, b: exact_tests.append(1) or real(a, b),
        )
        notifications = []
        file_cmd._editor.notification_requested.connect(
            lambda sender, **kwargs: notifications.append(kwargs), weak=False
        )

        with patch("swiftcut.doceditor.file_cmd.get_context") as mock_ctx:
            mock_ctx.return_value.config.machine.axis_extents = (1400, 900)
            for _ in range(2):
                result = DxfImporter(
                    LARGE_DXF.read_bytes(), LARGE_DXF
                ).get_doc_items(PassthroughSpec())
                assert result and result.payload
                items = file_cmd._get_positionable_content(
                    result.payload.items
                )
                exact_tests.clear()
                file_cmd._place_at_nearest_free_spot(items, None)
                for item in items:
                    file_cmd._editor.doc.active_layer.add_child(item)

        assert notifications == []
        assert 0 < len(exact_tests) < 10_000


class TestCommitItemsToDocument:
    """Tests for _commit_items_to_document method."""

    def test_commit_workpiece_to_document(self, file_cmd, sample_workpiece):
        """Test committing a WorkPiece to the document."""
        source = SourceAsset(
            source_file=Path("test.svg"),
            original_data=b"<svg></svg>",
            renderer=SVG_RENDERER,
        )
        filename = Path("test.svg")

        file_cmd._commit_items_to_document(
            [sample_workpiece], source, filename
        )

        assert source.uid in file_cmd._editor.doc.assets
        assert sample_workpiece in (file_cmd._editor.doc.active_layer.children)

    def test_commit_layer_to_document(self, file_cmd, sample_layer):
        """Test committing a Layer to the document."""
        source = SourceAsset(
            source_file=Path("test.svg"),
            original_data=b"<svg></svg>",
            renderer=SVG_RENDERER,
        )
        filename = Path("test.svg")

        file_cmd._commit_items_to_document([sample_layer], source, filename)

        assert source in file_cmd._editor.doc.get_all_assets()
        assert sample_layer in file_cmd._editor.doc.children


class TestFinalizeImportOnMainThread:
    """Tests for _finalize_import_on_main_thread method."""

    def test_finalize_import(self, file_cmd, sample_payload):
        """Test finalizing import on main thread."""
        filename = Path("test.svg")

        file_cmd._finalize_import_on_main_thread(
            sample_payload, filename, None
        )

        assert sample_payload.source.uid in file_cmd._editor.doc.assets
        assert sample_payload.items[0] in (
            file_cmd._editor.doc.active_layer.children
        )


class TestPreviewResult:
    """Tests for PreviewResult dataclass."""

    def test_preview_result_creation(self, sample_parse_result):
        """Test creating a PreviewResult instance."""
        result = PreviewResult(
            image_bytes=b"fake png data",
            payload=None,
            parse_result=sample_parse_result,
            aspect_ratio=1.5,
            warnings=["warning 1"],
        )

        assert result.image_bytes == b"fake png data"
        assert result.payload is None
        assert result.parse_result is sample_parse_result
        assert result.aspect_ratio == 1.5
        assert result.warnings == ["warning 1"]

    def test_preview_result_defaults(self):
        """Test PreviewResult default values."""
        result = PreviewResult(
            image_bytes=b"data", payload=None, parse_result=None
        )

        assert result.aspect_ratio == 1.0
        assert result.warnings == []


class TestGeneratePreview:
    """Tests for generate_preview method."""

    @pytest.mark.asyncio
    async def test_generate_preview_success(self, file_cmd):
        """Test successful preview generation."""
        with patch.object(
            file_cmd,
            "_generate_preview_impl",
            return_value=PreviewResult(
                image_bytes=b"png", payload=None, parse_result=None
            ),
        ):
            result = await file_cmd.generate_preview(
                b"data", "test.png", "image/png", TraceSpec(), 256
            )

            assert result is not None
            assert result.image_bytes == b"png"

    @pytest.mark.asyncio
    async def test_generate_preview_failure(self, file_cmd):
        """Test preview generation failure."""
        with patch.object(
            file_cmd, "_generate_preview_impl", return_value=None
        ):
            result = await file_cmd.generate_preview(
                b"data", "test.png", "image/png", TraceSpec(), 256
            )

            assert result is None


class TestGeneratePreviewImpl:
    """Tests for _generate_preview_impl method."""

    def test_preview_impl_no_import_result(self, file_cmd):
        """Test preview when importer returns None."""
        with patch(
            "swiftcut.image.base_importer.Importer.get_doc_items",
            return_value=None,
        ):
            result = file_cmd._generate_preview_impl(
                b"data", "test.png", "image/png", TraceSpec(), 256
            )
            assert result is None

    def test_preview_impl_no_workpiece(self, file_cmd, sample_import_result):
        """Test preview when no WorkPiece is found in the payload."""
        sample_import_result.payload.items = []
        with (
            patch(
                "swiftcut.image.base_importer.Importer.get_doc_items",
                return_value=sample_import_result,
            ),
            patch.object(
                file_cmd, "_generate_rich_preview_result"
            ) as mock_gen,
        ):
            file_cmd._generate_preview_impl(
                b"data", "test.png", "image/png", TraceSpec(), 256
            )
            # Should still call the generator, which can handle empty items
            mock_gen.assert_called_once()


class TestLoadFileAsync:
    """Tests for _load_file_async method."""

    @pytest.mark.asyncio
    async def test_load_file_async_success(
        self, file_cmd, sample_import_result
    ):
        """Test successful async file load."""
        with patch(
            "swiftcut.image.base_importer.Importer.get_doc_items",
            return_value=sample_import_result,
        ):
            result = await file_cmd._load_file_async(
                Path("tests") / "image" / "svg" / "o.svg",
                "image/svg+xml",
                None,
            )
            assert result is sample_import_result

    @pytest.mark.asyncio
    async def test_load_file_async_failure(self, file_cmd):
        """Test async file load failure."""
        with patch(
            "swiftcut.image.base_importer.Importer.get_doc_items",
            return_value=None,
        ):
            result = await file_cmd._load_file_async(
                Path("tests") / "image" / "svg" / "o.svg",
                "image/svg+xml",
                None,
            )
            assert result is None


class TestLoadFileFromPath:
    """Tests for load_file_from_path method."""

    def test_load_file_adds_task(self, file_cmd):
        """Test that load_file_from_path adds a task to the task manager."""
        filename = Path("test.svg")

        file_cmd.load_file_from_path(filename, "image/svg+xml", None, None)

        file_cmd._task_manager.add_coroutine.assert_called()


def _svg_mm(path: Path, width: float, height: float) -> Path:
    """Writes an SVG holding one width x height mm rectangle."""
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}mm" height="{height}mm" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="none" '
        'stroke="black" stroke-width="0.1"/></svg>'
    )
    return path


async def _wait_for_import(editor, task_mgr, timeout=30.0):
    """Waits until the import task and the pipeline are done."""
    deadline = time.monotonic() + timeout
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "import did not finish"
        await asyncio.sleep(0.01)
    await editor.wait_until_settled()


class TestOversizePolicy:
    """
    load_file_from_path asks the oversize policy, after loading, when
    the content is larger than the bed: Scale to fit or Cancel.
    """

    @pytest.fixture
    def bed(self, test_machine_and_config):
        """The ilab-614 bed: 1400 x 900 mm."""
        machine, _config = test_machine_and_config
        machine.set_axis_extents(1400, 900)
        return machine

    @pytest.mark.asyncio
    async def test_cancel_adds_nothing(
        self, doc_editor, task_mgr, bed, tmp_path
    ):
        path = _svg_mm(tmp_path / "big.svg", 2000, 1000)
        asked = []

        def policy(file_path, size_mm, bed_mm, answer):
            asked.append((file_path, size_mm, bed_mm))
            answer(False)

        doc_editor.file.oversize_policy = policy
        doc_editor.file.load_file_from_path(
            path, "image/svg+xml", PassthroughSpec()
        )
        await _wait_for_import(doc_editor, task_mgr)

        ((file_path, size_mm, bed_mm),) = asked
        assert file_path == path
        assert size_mm[0] > 1400
        assert bed_mm == (1400, 900)
        assert doc_editor.doc.all_workpieces == []
        assert doc_editor.doc.get_all_assets() == []

    @pytest.mark.asyncio
    async def test_scale_to_fit_fits_the_bed(
        self, doc_editor, task_mgr, bed, tmp_path
    ):
        path = _svg_mm(tmp_path / "big.svg", 2000, 1000)
        answers = []
        doc_editor.file.oversize_policy = (
            lambda file_path, size_mm, bed_mm, answer: answers.append(answer)
        )
        doc_editor.file.load_file_from_path(
            path, "image/svg+xml", PassthroughSpec()
        )

        # The question stays open while the loop runs on; nothing is
        # added until the answer comes.
        deadline = time.monotonic() + 30
        while not answers:
            assert time.monotonic() < deadline, "policy was not asked"
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        assert doc_editor.doc.all_workpieces == []

        answers[0](True)
        await _wait_for_import(doc_editor, task_mgr)

        (wp,) = doc_editor.doc.all_workpieces
        width, height = wp.size
        assert width <= 1400 + 1e-6
        assert height <= 900 + 1e-6
        assert max(width / 1400, height / 900) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_content_that_fits_is_never_asked_nor_scaled(
        self, doc_editor, task_mgr, bed, tmp_path
    ):
        path = _svg_mm(tmp_path / "fits.svg", 1000, 800)
        result = SvgImporter(path.read_bytes(), path).get_doc_items(
            PassthroughSpec()
        )
        assert result and result.payload
        content = doc_editor.file._get_positionable_content(
            result.payload.items
        )
        bbox = doc_editor.file._calculate_items_bbox(content)
        assert bbox
        policy = MagicMock()
        doc_editor.file.oversize_policy = policy

        doc_editor.file.load_file_from_path(
            path, "image/svg+xml", PassthroughSpec()
        )
        await _wait_for_import(doc_editor, task_mgr)

        policy.assert_not_called()
        (wp,) = doc_editor.doc.all_workpieces
        assert wp.size == pytest.approx(bbox[2:])


def _frame_centre(workpieces):
    """The centre of the union of the workpieces' frames."""
    x0 = min(wp.bbox[0] for wp in workpieces)
    y0 = min(wp.bbox[1] for wp in workpieces)
    x1 = max(wp.bbox[0] + wp.bbox[2] for wp in workpieces)
    y1 = max(wp.bbox[1] + wp.bbox[3] for wp in workpieces)
    return (x0 + x1) / 2, (y0 + y1) / 2


class TestImportPlacement:
    """
    An import goes to the free spot nearest to its target (the bed
    centre, or the drop point) as one piece, 1 mm clear of every
    workpiece already in the document.
    """

    @pytest.fixture
    def bed(self, test_machine_and_config):
        """The ilab-614 bed: 1400 x 900 mm."""
        machine, _config = test_machine_and_config
        machine.set_axis_extents(1400, 900)
        return machine

    async def _import(self, editor, task_mgr, path, position_mm=None):
        """Imports a file; returns the workpieces it added."""
        before = {wp.uid for wp in editor.doc.all_workpieces}
        editor.file.load_file_from_path(
            path, None, PassthroughSpec(), position_mm
        )
        await _wait_for_import(editor, task_mgr)
        return [wp for wp in editor.doc.all_workpieces if wp.uid not in before]

    @pytest.mark.asyncio
    async def test_same_file_twice_sits_next_to_the_first(
        self, doc_editor, task_mgr, bed, tmp_path
    ):
        path = _svg_mm(tmp_path / "part.svg", 100, 60)

        (first,) = await self._import(doc_editor, task_mgr, path)
        (second,) = await self._import(doc_editor, task_mgr, path)

        assert _frame_centre([first]) == pytest.approx((700, 450))
        # Directly below the first (nearest; ties go lower), its outline
        # 1 mm clear and touching that clearance. (The SVG frame pads
        # the outline by 1 mm, so the frames may overlap.)
        assert _frame_centre([second])[0] == pytest.approx(700)
        (upper,) = item_world_polygons(first)
        (lower,) = item_world_polygons(second)
        gap = min(y for _x, y in upper) - max(y for _x, y in lower)
        assert 1.0 <= gap < 1.2

    @pytest.mark.asyncio
    async def test_full_bed_overlaps_at_the_centre_with_a_notice(
        self, doc_editor, task_mgr, bed, tmp_path
    ):
        cover = WorkPiece(name="Cover")
        cover.set_size(1400, 900)
        cover.pos = (0, 0)
        doc_editor.doc.add_workpiece(cover)
        notices = []
        doc_editor.notification_requested.connect(
            lambda sender, **kwargs: notices.append(kwargs["message"]),
            weak=False,
        )
        path = _svg_mm(tmp_path / "part.svg", 100, 60)

        (wp,) = await self._import(doc_editor, task_mgr, path)

        assert _frame_centre([wp]) == pytest.approx((700, 450))
        assert notices == [
            "No free space on the bed: the import overlaps other pieces."
        ]

    @pytest.mark.asyncio
    async def test_free_target_is_kept_without_a_notice(
        self, doc_editor, task_mgr, bed, tmp_path
    ):
        notices = []
        doc_editor.notification_requested.connect(
            lambda sender, **kwargs: notices.append(kwargs["message"]),
            weak=False,
        )
        path = _svg_mm(tmp_path / "part.svg", 100, 60)
        await self._import(doc_editor, task_mgr, path)

        (wp,) = await self._import(doc_editor, task_mgr, path, (200, 150))

        assert _frame_centre([wp]) == pytest.approx((200, 150))
        assert notices == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "corner", [(0, 0), (1400, 0), (0, 900), (1400, 900)]
    )
    async def test_a_drop_on_a_bed_corner_lands_inside(
        self, doc_editor, task_mgr, bed, tmp_path, corner
    ):
        path = _svg_mm(tmp_path / "part.svg", 100, 60)

        (wp,) = await self._import(doc_editor, task_mgr, path, corner)

        x, y, w, h = wp.bbox
        assert inside(wp.bbox, (0, 0, 1400, 900))
        # In the corner: on both its edges.
        assert (x if corner[0] == 0 else x + w) == pytest.approx(corner[0])
        assert (y if corner[1] == 0 else y + h) == pytest.approx(corner[1])

    @pytest.mark.asyncio
    async def test_multi_item_file_keeps_its_layout(
        self, doc_editor, task_mgr, bed
    ):
        result = LightBurnImporter(
            SWITCH_PLATE.read_bytes(), SWITCH_PLATE
        ).get_doc_items(PassthroughSpec())
        assert result and result.payload
        layout = {
            wp.name: wp.pos
            for wp in doc_editor.file._get_positionable_content(
                result.payload.items
            )
        }
        assert len(layout) == 2
        block = WorkPiece(name="Block")
        block.set_size(300, 300)
        block.pos = (550, 300)
        doc_editor.doc.add_workpiece(block)

        added = await self._import(doc_editor, task_mgr, SWITCH_PLATE)

        assert len(added) == 2
        plate, holes = sorted(added, key=lambda wp: wp.name, reverse=True)
        dx = holes.pos[0] - plate.pos[0]
        dy = holes.pos[1] - plate.pos[1]
        assert (dx, dy) == pytest.approx(
            (
                layout[holes.name][0] - layout[plate.name][0],
                layout[holes.name][1] - layout[plate.name][1],
            )
        )
        # Moved off the block, 1 mm clear, still on the bed.
        x, y, w, h = plate.bbox
        assert (
            x + w <= 550 - 1.0
            or x >= 850 + 1.0
            or y + h <= 300 - 1.0
            or y >= 600 + 1.0
        )
        assert 0 <= x and x + w <= 1400 and 0 <= y and y + h <= 900


class TestExportGcodeToPath:
    """Tests for export_gcode_to_path method."""

    def test_export_gcode_failure(self, file_cmd, tmp_path):
        """Test G-code export failure."""
        export_path = tmp_path / "output.gcode"

        with patch.object(
            file_cmd._editor.pipeline, "generate_job_artifact"
        ) as mock_generate:

            def failure_callback(when_done):
                when_done(None, Exception("Export failed"))

            mock_generate.side_effect = failure_callback
            file_cmd.export_gcode_to_path(export_path)

            assert not export_path.exists()


class TestGetImporterInfo:
    """Tests for the get_importer_info method."""

    def test_get_info_by_mime(self, file_cmd):
        """Test finding an importer and its features by MIME type."""
        mock_importer = MagicMock()
        mock_importer.features = {ImporterFeature.DIRECT_VECTOR}
        with patch(
            "swiftcut.doceditor.file_cmd.importer_registry.get_by_mime_type",
            return_value=mock_importer,
        ):
            # A registered extension wins over the MIME type, so the
            # MIME lookup only decides for an unregistered suffix.
            cls, features = file_cmd.get_importer_info(
                Path("f.unknown"), "image/vnd.dxf"
            )
            assert cls is mock_importer
            assert features == {ImporterFeature.DIRECT_VECTOR}

    def test_get_info_by_extension(self, file_cmd):
        """Test fallback to extension matching."""
        mock_importer = MagicMock()
        mock_importer.features = {ImporterFeature.BITMAP_TRACING}
        with (
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry."
                "get_by_mime_type",
                return_value=None,
            ),
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry"
                ".get_by_extension",
                return_value=mock_importer,
            ),
        ):
            cls, features = file_cmd.get_importer_info(Path("f.png"), None)
            assert cls is mock_importer
            assert features == {ImporterFeature.BITMAP_TRACING}

    def test_get_info_not_found(self, file_cmd):
        """Test case where no importer is found."""
        with (
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry."
                "get_by_mime_type",
                return_value=None,
            ),
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry"
                ".get_by_extension",
                return_value=None,
            ),
        ):
            cls, features = file_cmd.get_importer_info(
                Path("f.txt"), "text/plain"
            )
            assert cls is None
            assert features == set()


class TestImporterForRealFiles:
    """
    get_importer_info against the real importer registry. macOS reports
    .dxf and .lbrn2 as application/octet-stream (file dialog) or as a
    dyn.* type (drop); the extension must still pick the importer.
    """

    @pytest.mark.parametrize(
        "path, mime_type, expected",
        [
            (LARGE_DXF, "application/octet-stream", DxfImporter),
            (LARGE_DXF, "dyn.age80k8dg", DxfImporter),
            (SWITCH_PLATE, "application/octet-stream", LightBurnImporter),
            (Path("job.rd"), "application/octet-stream", RuidaImporter),
        ],
        ids=["dxf-octet-stream", "dxf-uti", "lbrn2-octet-stream", "rd"],
    )
    def test_extension_picks_the_importer(
        self, file_cmd, path, mime_type, expected
    ):
        cls, _ = file_cmd.get_importer_info(path, mime_type)
        assert cls is expected

    def test_mime_type_decides_without_extension(self, file_cmd):
        cls, _ = file_cmd.get_importer_info(Path("drawing"), "image/svg+xml")
        assert cls is SvgImporter


class TestAnalyzeImportTarget:
    """Tests for analyze_import_target method."""

    def test_analyze_svg(self, file_cmd):
        """Test that SVG files trigger interactive config."""
        path = Path("test.svg")
        mock_importer = MagicMock()
        mock_importer.features = {
            ImporterFeature.DIRECT_VECTOR,
            ImporterFeature.BITMAP_TRACING,
            ImporterFeature.LAYER_SELECTION,
        }
        with patch(
            "swiftcut.doceditor.file_cmd.importer_registry.get_by_mime_type",
            return_value=mock_importer,
        ):
            action = file_cmd.analyze_import_target(path, "image/svg+xml")
            assert action == ImportAction.INTERACTIVE_CONFIG

    def test_analyze_png(self, file_cmd):
        """Test that PNG files trigger interactive config."""
        path = Path("test.png")
        mock_importer = MagicMock()
        mock_importer.features = {ImporterFeature.BITMAP_TRACING}
        with patch(
            "swiftcut.doceditor.file_cmd.importer_registry.get_by_mime_type",
            return_value=mock_importer,
        ):
            action = file_cmd.analyze_import_target(path, "image/png")
            assert action == ImportAction.INTERACTIVE_CONFIG

    def test_analyze_dxf(self, file_cmd):
        """Test that DXF files trigger interactive config (due to layers)."""
        path = Path("test.dxf")
        mock_importer = MagicMock()
        mock_importer.features = {
            ImporterFeature.DIRECT_VECTOR,
            ImporterFeature.LAYER_SELECTION,
        }

        # Test with explicit mime
        with patch(
            "swiftcut.doceditor.file_cmd.importer_registry.get_by_mime_type",
            return_value=mock_importer,
        ):
            action = file_cmd.analyze_import_target(path, "image/vnd.dxf")
            assert action == ImportAction.INTERACTIVE_CONFIG

        # Test extension fallback
        with patch(
            "swiftcut.doceditor.file_cmd.importer_registry.get_by_extension",
            return_value=mock_importer,
        ):
            action = file_cmd.analyze_import_target(path, None)
            assert action == ImportAction.INTERACTIVE_CONFIG

    def test_analyze_unsupported(self, file_cmd):
        """Test that unknown files return unsupported."""
        path = Path("test.exe")
        # Ensure no importers match
        with (
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry."
                "get_by_mime_type",
                return_value=None,
            ),
            patch(
                "swiftcut.doceditor.file_cmd.importer_registry"
                ".get_by_extension",
                return_value=None,
            ),
        ):
            action = file_cmd.analyze_import_target(
                path, "application/octet-stream"
            )
            assert action == ImportAction.UNSUPPORTED


class TestExecuteBatchImport:
    """Tests for execute_batch_import method."""

    def test_execute_batch_import(self, file_cmd):
        """Test that batch import spawns individual load tasks."""
        files = [Path("test1.png"), Path("test2.jpg")]
        spec = TraceSpec()
        pos = (10.0, 10.0)

        with patch.object(file_cmd, "load_file_from_path") as mock_load:
            file_cmd.execute_batch_import(files, spec, pos)

            assert mock_load.call_count == 2

            # Verify calls
            mock_load.assert_any_call(files[0], "image/png", spec, pos)
            mock_load.assert_any_call(files[1], "image/jpeg", spec, pos)


class TestProjectRoundTrip:
    """Tests for save_project_to_path and load_project_from_path round trip."""

    def _compare_docs(self, doc1, doc2):
        """Compare two documents for equality."""
        assert doc1.uid == doc2.uid
        assert doc1._active_layer_index == doc2._active_layer_index
        assert len(doc1.children) == len(doc2.children)
        assert len(doc1.assets) == len(doc2.assets)
        assert len(doc1.asset_order) == len(doc2.asset_order)

    def _compare_layers(self, layer1, layer2):
        """Compare two layers for equality."""
        assert layer1.uid == layer2.uid
        assert layer1.name == layer2.name
        assert layer1.visible == layer2.visible
        assert layer1.extra.get("stock_item_uid") == layer2.extra.get(
            "stock_item_uid"
        )
        assert len(layer1.children) == len(layer2.children)

    def _compare_workpieces(self, wp1, wp2):
        """Compare two workpieces for equality."""
        assert wp1.uid == wp2.uid
        assert wp1.name == wp2.name
        assert wp1.natural_width_mm == wp2.natural_width_mm
        assert wp1.natural_height_mm == wp2.natural_height_mm
        assert wp1.tabs_enabled == wp2.tabs_enabled
        assert wp1.geometry_provider_uid == wp2.geometry_provider_uid
        assert wp1.source_asset_uid == wp2.source_asset_uid
        assert len(wp1.tabs) == len(wp2.tabs)

    def _compare_groups(self, group1, group2):
        """Compare two groups for equality."""
        assert group1.uid == group2.uid
        assert group1.name == group2.name
        assert len(group1.children) == len(group2.children)

    def _compare_stock_items(self, item1, item2):
        """Compare two stock items for equality."""
        assert item1.uid == item2.uid
        assert item1.name == item2.name
        assert item1.stock_asset_uid == item2.stock_asset_uid
        assert item1.visible == item2.visible

    def _compare_assets(self, asset1, asset2):
        """Compare two assets for equality."""
        assert asset1.uid == asset2.uid
        assert asset1.name == asset2.name
        assert asset1.asset_type_name == asset2.asset_type_name

    def test_round_trip_minimal_project(self, file_cmd, tmp_path):
        """Test round trip for minimal project with single layer."""
        import_file = Path(__file__).parent / "assets" / "minimal_project.ryp"
        export_file = tmp_path / "minimal_export.ryp"

        # Import project
        result = file_cmd.load_project_from_path(import_file)
        assert result is True

        # Export project
        result = file_cmd.save_project_to_path(export_file)
        assert result is True
        assert export_file.exists()

        # Import exported project
        result = file_cmd.load_project_from_path(export_file)
        assert result is True

    def test_round_trip_multiple_layers(self, file_cmd, tmp_path):
        """Test round trip for project with multiple layers."""
        import_file = Path(__file__).parent / "assets" / "multiple_layers.ryp"
        export_file = tmp_path / "multiple_layers_export.ryp"

        # Import project
        result = file_cmd.load_project_from_path(import_file)
        assert result is True

        # Verify layers loaded correctly
        assert len(file_cmd._editor.doc.layers) == 3
        assert file_cmd._editor.doc.layers[0].name == "Layer 1"
        assert file_cmd._editor.doc.layers[1].name == "Layer 2"
        assert file_cmd._editor.doc.layers[2].name == "Layer 3"
        assert file_cmd._editor.doc.layers[2].visible is False

        # Export project
        result = file_cmd.save_project_to_path(export_file)
        assert result is True
        assert export_file.exists()

        # Import exported project
        result = file_cmd.load_project_from_path(export_file)
        assert result is True

        # Verify layers after round trip
        assert len(file_cmd._editor.doc.layers) == 3
        assert file_cmd._editor.doc.layers[2].visible is False

    def test_round_trip_workpieces(self, file_cmd, tmp_path):
        """Test round trip for project with workpieces."""
        import_file = (
            Path(__file__).parent / "assets" / "workpieces_project.ryp"
        )
        export_file = tmp_path / "workpieces_export.ryp"

        # Import project
        result = file_cmd.load_project_from_path(import_file)
        assert result is True

        # Verify workpieces loaded
        workpieces = file_cmd._editor.doc.all_workpieces
        assert len(workpieces) == 2
        assert workpieces[0].name == "Rectangle"
        assert workpieces[1].name == "Circle"

        # Export project
        result = file_cmd.save_project_to_path(export_file)
        assert result is True
        assert export_file.exists()

        # Import exported project
        result = file_cmd.load_project_from_path(export_file)
        assert result is True

        # Verify workpieces after round trip
        workpieces = file_cmd._editor.doc.all_workpieces
        assert len(workpieces) == 2
        assert workpieces[0].natural_width_mm == 10.0
        assert workpieces[1].natural_width_mm == 20.0

    def test_round_trip_groups(self, file_cmd, tmp_path):
        """Test round trip for project with groups."""
        import_file = Path(__file__).parent / "assets" / "groups_project.ryp"
        export_file = tmp_path / "groups_export.ryp"

        # Import project
        result = file_cmd.load_project_from_path(import_file)
        assert result is True

        # Verify groups loaded
        groups = [
            c
            for c in file_cmd._editor.doc.get_descendants()
            if isinstance(c, Group)
        ]
        assert len(groups) == 3

        # Export project
        result = file_cmd.save_project_to_path(export_file)
        assert result is True
        assert export_file.exists()

        # Import exported project
        result = file_cmd.load_project_from_path(export_file)
        assert result is True

        # Verify groups after round trip
        groups = [
            c
            for c in file_cmd._editor.doc.get_descendants()
            if isinstance(c, Group)
        ]
        assert len(groups) == 3

    def test_round_trip_stock(self, file_cmd, tmp_path):
        """Test round trip for project with stock items."""
        import_file = Path(__file__).parent / "assets" / "stock_project.ryp"
        export_file = tmp_path / "stock_export.ryp"

        # Import project
        result = file_cmd.load_project_from_path(import_file)
        assert result is True

        # Verify stock items loaded
        stock_items = file_cmd._editor.doc.stock_items
        assert len(stock_items) == 2
        assert stock_items[0].name == "Plywood Sheet"
        assert stock_items[1].name == "Acrylic Sheet"
        assert stock_items[1].visible is False

        # Verify stock assets loaded
        stock_assets = [
            a
            for a in file_cmd._editor.doc.get_all_assets()
            if isinstance(a, StockAsset)
        ]
        assert len(stock_assets) == 2
        assert stock_assets[0].thickness == 18.0
        assert stock_assets[1].thickness == 5.0

        # Export project
        result = file_cmd.save_project_to_path(export_file)
        assert result is True
        assert export_file.exists()

        # Import exported project
        result = file_cmd.load_project_from_path(export_file)
        assert result is True

        # Verify stock after round trip
        stock_items = file_cmd._editor.doc.stock_items
        assert len(stock_items) == 2
        assert stock_items[1].visible is False

    def test_round_trip_comprehensive(self, file_cmd, tmp_path):
        """Test round trip for comprehensive project with all features."""
        import_file = (
            Path(__file__).parent / "assets" / "comprehensive_project.ryp"
        )
        export_file = tmp_path / "comprehensive_export.ryp"

        # Import project
        result = file_cmd.load_project_from_path(import_file)

        assert result is True

        # Verify comprehensive features loaded
        assert len(file_cmd._editor.doc.layers) == 2
        assert file_cmd._editor.doc._active_layer_index == 1
        assert len(file_cmd._editor.doc.stock_items) == 2
        assert len(file_cmd._editor.doc.all_workpieces) == 2

        # Export project
        result = file_cmd.save_project_to_path(export_file)
        assert result is True
        assert export_file.exists()

        # Import exported project
        result = file_cmd.load_project_from_path(export_file)
        assert result is True

        # Verify comprehensive features after round trip
        assert len(file_cmd._editor.doc.layers) == 2
        assert file_cmd._editor.doc._active_layer_index == 1
        assert len(file_cmd._editor.doc.stock_items) == 2
        assert len(file_cmd._editor.doc.all_workpieces) == 2

    def test_round_trip_all_project_files(self, file_cmd, tmp_path):
        """
        Test round trip for all project files in assets directory.
        Skips files that require sketcher addon if not available.
        """
        assets_dir = Path(__file__).parent / "assets"
        project_files = list(assets_dir.glob("*.ryp"))

        assert len(project_files) > 0, "No .ryp files found in assets"

        for project_file in project_files:
            export_file = tmp_path / f"{project_file.stem}_export.ryp"

            # Import project
            result = file_cmd.load_project_from_path(project_file)
            assert result is True, f"Failed to load {project_file.name}"

            # Capture document state before round trip
            doc_dict_before = file_cmd._editor.doc.to_dict()

            # Export project
            result = file_cmd.save_project_to_path(export_file)
            assert result is True, f"Failed to save {project_file.name}"
            assert export_file.exists()

            # Import exported project (round trip)
            result = file_cmd.load_project_from_path(export_file)
            assert result is True, (
                f"Failed to load exported {project_file.stem}"
            )

            # Capture document state after round trip
            doc_dict_after = file_cmd._editor.doc.to_dict()

            # Compare documents as a whole
            assert doc_dict_before == doc_dict_after, (
                f"Document state changed after round trip for "
                f"{project_file.name}"
            )


class TestExportRdToPath:
    """The .rd export writes what the machine would have received."""

    def _ruida_machine(self, context):
        """A machine whose driver is the Ruida one."""
        from swiftcut.machine.models.laser import Laser

        machine = Machine(context)
        machine.driver_name = "RuidaDriver"
        laser = Laser()
        machine.heads.clear()
        machine.add_head(laser)
        return machine

    def _square_job_ops(self):
        from raygeo.ops import Ops

        ops = Ops()
        ops.job_start()
        ops.layer_start("layer-1")
        ops.set_power(0.6)
        ops.set_feed_rate(600)
        ops.move_to(0.0, 0.0, 0.0)
        ops.line_to(10.0, 0.0, 0.0)
        ops.line_to(10.0, 10.0, 0.0)
        ops.layer_end("layer-1")
        ops.job_end()
        return ops

    def _export(self, file_cmd, context, machine, ops, export_path):
        """Drive the export with a stubbed job artifact."""
        from contextlib import contextmanager

        from swiftcut.pipeline.artifact import JobArtifact

        artifact = JobArtifact(ops=ops, distance=0.0, generation_id=1)

        @contextmanager
        def checkout_handle(_handle):
            yield artifact

        context.config.set_machine(machine)
        with (
            patch.object(
                file_cmd._editor.pipeline.artifact_store,
                "checkout_handle",
                checkout_handle,
            ),
            patch.object(
                file_cmd._editor.pipeline, "generate_job_artifact"
            ) as mock_generate,
        ):
            mock_generate.side_effect = lambda when_done: when_done(
                MagicMock(), None
            )
            file_cmd.export_rd_to_path(export_path)

    def test_export_writes_the_send_job_blob(
        self, file_cmd, context_initializer, tmp_path
    ):
        """The file equals build_rd_bytes on the production ops.

        build_rd_bytes is the call RuidaDriver.run makes, and
        test_export_writes_the_same_blob_as_send ties that to what
        send_job actually transmits.
        """
        from swiftcut.machine.driver.ruida.ruida_encoder import build_rd_bytes

        machine = self._ruida_machine(context_initializer)
        ops = self._square_job_ops()
        export_path = tmp_path / "job.rd"

        self._export(file_cmd, context_initializer, machine, ops, export_path)

        assert export_path.exists()
        assert export_path.read_bytes() == build_rd_bytes(
            ops, machine, file_cmd._editor.doc
        )

    def test_export_does_not_read_pipeline_driver_data(
        self, file_cmd, context_initializer, tmp_path
    ):
        """The pipeline strips driver_data, so it cannot be the source.

        The artifact here carries none at all -- exactly what reaches
        the UI -- and the export must still succeed.
        """
        machine = self._ruida_machine(context_initializer)
        ops = self._square_job_ops()
        export_path = tmp_path / "job.rd"

        self._export(file_cmd, context_initializer, machine, ops, export_path)

        assert export_path.read_bytes()
