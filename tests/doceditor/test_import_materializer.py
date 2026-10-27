"""
Import as: the four groupings through FileCmd's real import path,
on the import fixtures (tests/fixtures/import).
"""

import asyncio
import base64
import time
from pathlib import Path

import numpy as np
import pytest
import pyvips

from swiftcut.core.recipe import Recipe
from swiftcut.core.recipe_manager import RecipeManager
from swiftcut.core.stock import StockItem
from swiftcut.core.stock_asset import StockAsset
from swiftcut.core.vectorization_spec import LayerImportMode, PassthroughSpec
from swiftcut.doceditor.import_materializer import (
    ImportGrouping,
    ImportOptions,
    effective_grouping,
    image_is_placeable,
    looks_traced,
    skipped_image_warnings,
)
from swiftcut.image.dxf.importer import DxfImporter
from swiftcut.image.svg.importer import SvgImporter

TESTS_DIR = Path(__file__).parent.parent
FIXTURES = TESTS_DIR / "fixtures" / "import"
ILLUSTRATOR = FIXTURES / "illustrator_two_layers.svg"
TRACED = FIXTURES / "illustrator_traced.dxf"
PLATES = FIXTURES / "cad_plate.dxf"
MM_PER_PT = 25.4 / 72

BY_SOURCE = ImportOptions(grouping=ImportGrouping.BY_SOURCE)


async def _wait_for_import(editor, task_mgr, timeout=60.0):
    """Waits until the import task and the pipeline are done."""
    deadline = time.monotonic() + timeout
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "import did not finish"
        await asyncio.sleep(0.01)
    await editor.wait_until_settled()


@pytest.fixture
def bed(test_machine_and_config):
    """The ilab-614 bed: 1400 x 900 mm."""
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


@pytest.fixture
def sent(doc_editor):
    """What items_imported sends, one dict per import."""
    sent = []
    doc_editor.file.items_imported.connect(
        lambda sender, **kwargs: sent.append(kwargs), weak=False
    )
    return sent


def _illustrator_spec(**kwargs):
    """The dialog's spec for the Illustrator file: its layers, 72 ppi."""
    return PassthroughSpec(
        active_layer_ids=["Cut", "Engrave"], ppi=72, **kwargs
    )


async def _import(editor, task_mgr, path, spec=None, options=None):
    """Imports a file; returns the workpieces it added."""
    before = {wp.uid for wp in editor.doc.all_workpieces}
    editor.file.load_file_from_path(
        path, None, spec or PassthroughSpec(), options=options
    )
    await _wait_for_import(editor, task_mgr)
    return [wp for wp in editor.doc.all_workpieces if wp.uid not in before]


def _box(wp):
    """A workpiece's world box (x0, y0, x1, y1)."""
    return wp.get_world_geometry().rect()


def _contours(wp) -> int:
    return len(wp.boundaries.split_into_contours())


class TestBySource:
    @pytest.mark.asyncio
    async def test_illustrator_layers_groups_and_image(
        self, doc_editor, task_mgr, bed, sent
    ):
        """
        Two layers, Cut and Engrave. Engrave's Logo (3 shapes) and Text
        (2 letters, the O with its hole) are one piece each; the placed
        PNG is an image workpiece.
        """
        layers_before = len(doc_editor.doc.layers)

        added = await _import(
            doc_editor, task_mgr, ILLUSTRATOR, _illustrator_spec(), BY_SOURCE
        )

        new_layers = doc_editor.doc.layers[layers_before:]
        assert [layer.name for layer in new_layers] == ["Cut", "Engrave"]
        cut, engrave = new_layers
        (outline,) = cut.all_workpieces
        logo, text, image = engrave.all_workpieces
        assert len(added) == 4
        assert [_contours(wp) for wp in (outline, logo, text)] == [1, 3, 3]
        assert (outline.source_layer, outline.source_color) == (
            "Cut",
            "#ff0000",
        )
        assert (logo.source_layer, logo.source_color) == ("Engrave", "#231f20")
        assert (text.source_layer, text.source_color) == ("Engrave", "#000000")
        assert (image.source_layer, image.source_color) == ("Engrave", None)
        assert image.source.renderer is not outline.source.renderer
        assert sent == [{"items": added, "individual": True}]

    @pytest.mark.asyncio
    async def test_the_image_lies_where_the_file_shows_it(
        self, doc_editor, task_mgr, bed
    ):
        """
        The outline's rect is 36..396 x 36..252 pt (y down); the PNG
        shows 234..270 x 108..144 pt (its clip). So in mm (25.4 / 72
        per pt), its left edge is (234 - 36) pt = 69.85 mm right of
        the outline's, its top (108 - 36) pt = 25.4 mm under the
        outline's, and it is 36 pt = 12.7 mm square.
        """
        await _import(
            doc_editor, task_mgr, ILLUSTRATOR, _illustrator_spec(), BY_SOURCE
        )
        cut, engrave = doc_editor.doc.layers[-2:]
        (outline,) = cut.all_workpieces
        image = engrave.all_workpieces[-1]

        ox0, _oy0, _ox1, oy1 = _box(outline)
        ix0, iy0, ix1, iy1 = _box(image)

        assert ix0 - ox0 == pytest.approx(198 * MM_PER_PT, abs=0.05)
        assert oy1 - iy1 == pytest.approx(72 * MM_PER_PT, abs=0.05)
        assert ix1 - ix0 == pytest.approx(36 * MM_PER_PT, abs=0.05)
        assert iy1 - iy0 == pytest.approx(36 * MM_PER_PT, abs=0.05)
        assert image.size == pytest.approx((12.7, 12.7), abs=0.05)

    @pytest.mark.asyncio
    async def test_without_images(self, doc_editor, task_mgr, bed):
        options = ImportOptions(
            grouping=ImportGrouping.BY_SOURCE, keep_images=False
        )

        added = await _import(
            doc_editor, task_mgr, ILLUSTRATOR, _illustrator_spec(), options
        )

        assert len(added) == 3
        assert all(wp.source.source_file == ILLUSTRATOR for wp in added)

    @pytest.mark.asyncio
    async def test_flatten_puts_everything_on_the_current_layer(
        self, doc_editor, task_mgr, bed
    ):
        options = ImportOptions(
            grouping=ImportGrouping.BY_SOURCE, layer_per_source_layer=False
        )
        layers = list(doc_editor.doc.layers)

        added = await _import(
            doc_editor, task_mgr, ILLUSTRATOR, _illustrator_spec(), options
        )

        assert doc_editor.doc.layers == layers
        assert len(added) == 4
        assert all(wp.layer is doc_editor.doc.active_layer for wp in added)

    @pytest.mark.asyncio
    async def test_a_flat_cad_file_comes_in_as_pieces(
        self, doc_editor, task_mgr, bed
    ):
        """
        cad_plate.dxf has one layer and no blocks: BY_SOURCE has
        nothing to go by and imports it as PIECES, one per plate,
        each outline (of LINEs and ARCs) with its holes.
        """
        tree = DxfImporter(PLATES.read_bytes(), PLATES).build_tree()

        added = await _import(doc_editor, task_mgr, PLATES, options=BY_SOURCE)

        assert effective_grouping(tree, ImportGrouping.BY_SOURCE) is (
            ImportGrouping.PIECES
        )
        assert sorted(_contours(wp) for wp in added) == [4, 5]
        assert sorted(wp.size for wp in added) == [
            pytest.approx((80, 50)),
            pytest.approx((100, 60)),
        ]
        for wp in added:
            assert all(
                c.is_closed() for c in wp.boundaries.split_into_contours()
            )


@pytest.mark.asyncio
async def test_groups_outside_layers_land_on_the_current_layer(
    doc_editor, task_mgr, bed, tmp_path
):
    """
    A file without layers but with a group keeps BY_SOURCE: the group
    is one piece, the loose rect another, both on the current layer.
    """
    path = tmp_path / "unlayered.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="100mm" viewBox="0 0 100 100"><g>'
        '<rect x="10" y="10" width="20" height="20" fill="none" '
        'stroke="#000"/><rect x="40" y="10" width="10" height="10" '
        'fill="none" stroke="#000"/></g><rect x="60" y="60" '
        'width="30" height="30" fill="none" stroke="#f00"/></svg>'
    )
    tree = SvgImporter(path.read_bytes(), path).build_tree()
    layers = list(doc_editor.doc.layers)

    added = await _import(doc_editor, task_mgr, path, options=BY_SOURCE)

    assert tree.layers() == []
    assert effective_grouping(tree, ImportGrouping.BY_SOURCE) is (
        ImportGrouping.BY_SOURCE
    )
    assert doc_editor.doc.layers == layers
    assert sorted(_contours(wp) for wp in added) == [1, 2]
    assert all(wp.layer is doc_editor.doc.active_layer for wp in added)


def test_layers_or_groups_keep_by_source():
    svg = SvgImporter(ILLUSTRATOR.read_bytes(), ILLUSTRATOR).build_tree(72)
    one_layer = SvgImporter(
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 9">'
        b'<g id="L"><g><rect width="1" height="1"/></g></g></svg>'
    ).build_tree()

    for tree in (svg, one_layer):
        assert effective_grouping(tree, ImportGrouping.BY_SOURCE) is (
            ImportGrouping.BY_SOURCE
        )
    assert effective_grouping(None, ImportGrouping.BY_SOURCE) is (
        ImportGrouping.PIECES
    )
    assert effective_grouping(svg, ImportGrouping.SINGLE) is (
        ImportGrouping.SINGLE
    )


class TestPieces:
    @pytest.mark.asyncio
    async def test_traced_artwork_inside_its_outline_on_an_engrave_layer(
        self, doc_editor, task_mgr, bed, sent
    ):
        """
        The traced DXF is one piece: the red outline is its boundary;
        the 120 black dots inside are its interior, a workpiece of its
        own on the "<file> engrave" layer.
        """
        options = ImportOptions(
            grouping=ImportGrouping.PIECES, interior_on_own_layer=True
        )
        layers_before = len(doc_editor.doc.layers)

        added = await _import(doc_editor, task_mgr, TRACED, options=options)

        outline, dots = added
        assert outline.layer is doc_editor.doc.layers[0]
        (engrave,) = doc_editor.doc.layers[layers_before:]
        assert engrave.name == "illustrator_traced engrave"
        assert engrave.all_workpieces == [dots]
        assert engrave.workflow.has_steps()
        assert (_contours(outline), _contours(dots)) == (1, 120)
        assert outline.size == pytest.approx((120, 80))
        assert outline.source_color == "#ff0000"
        assert dots.source_color == "#000000"
        assert sent == [{"items": added, "individual": True}]

    @pytest.mark.asyncio
    async def test_a_piece_keeps_its_interior_by_default(
        self, doc_editor, task_mgr, bed
    ):
        options = ImportOptions(grouping=ImportGrouping.PIECES)

        (piece,) = await _import(doc_editor, task_mgr, TRACED, options=options)

        assert _contours(piece) == 121
        assert piece.source_layer == "0"

    @pytest.mark.asyncio
    async def test_a_lone_piece_is_cut_to_its_paths(
        self, doc_editor, task_mgr, bed, tmp_path
    ):
        """
        A clipPath outside <defs> is no path (visible_svg moves it into
        <defs>): the layer's workpiece is the rect alone, and the one
        piece, cut from it as a lone fragment, is the rect.
        """
        path = tmp_path / "lone.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
            'height="100mm" viewBox="0 0 100 100"><g id="L">'
            '<clipPath id="c"><rect x="50" y="50" width="30" '
            'height="30"/></clipPath>'
            '<rect x="10" y="10" width="20" height="10" fill="none" '
            'stroke="#00f"/></g></svg>'
        )
        (single,) = await _import(doc_editor, task_mgr, path)
        options = ImportOptions(grouping=ImportGrouping.PIECES)

        (piece,) = await _import(doc_editor, task_mgr, path, options=options)

        assert single.size == pytest.approx((20, 10))
        assert _contours(single) == 1
        assert piece.size == pytest.approx((20, 10))
        assert _contours(piece) == 1
        assert (piece.source_layer, piece.source_color) == ("L", "#0000ff")


class TestOneUndoStep:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "grouping", [ImportGrouping.PIECES, ImportGrouping.BY_SOURCE]
    )
    async def test_everything_in_one_transaction_and_one_signal(
        self, doc_editor, task_mgr, bed, sent, grouping
    ):
        options = ImportOptions(grouping=grouping, interior_on_own_layer=True)
        history = doc_editor.history_manager
        entries = len(history.undo_stack)
        layers = list(doc_editor.doc.layers)

        added = await _import(
            doc_editor, task_mgr, ILLUSTRATOR, _illustrator_spec(), options
        )

        assert len(added) > 2
        assert len(history.undo_stack) == entries + 1
        assert sent == [{"items": added, "individual": True}]

        history.undo()

        assert doc_editor.doc.all_workpieces == []
        assert doc_editor.doc.layers == layers


class TestIndividual:
    @pytest.mark.asyncio
    async def test_each_shape_knows_its_layer_and_color(
        self, doc_editor, task_mgr, bed
    ):
        """
        With a tree (the file has an image to keep), each path piece
        gets the source layer and color of its path.
        """
        options = ImportOptions(grouping=ImportGrouping.INDIVIDUAL)
        spec = _illustrator_spec(layer_import_mode=LayerImportMode.FLATTEN)

        added = await _import(doc_editor, task_mgr, ILLUSTRATOR, spec, options)

        by_origin = sorted(
            (wp.source_layer, wp.source_color or "") for wp in added
        )
        assert by_origin == [
            ("Cut", "#ff0000"),
            ("Engrave", ""),
            *[("Engrave", "#000000")] * 3,
            *[("Engrave", "#231f20")] * 3,
        ]

    @pytest.mark.asyncio
    async def test_without_options_split_paths_is_as_before(
        self, doc_editor, task_mgr, bed, sent
    ):
        """No options: no placed image; each shape knows its layer."""
        doc_editor.file.load_file_from_path(
            ILLUSTRATOR, None, _illustrator_spec(), split_paths=True
        )
        await _wait_for_import(doc_editor, task_mgr)
        added = doc_editor.doc.all_workpieces

        assert len(added) == 7
        assert {wp.source_layer for wp in added} == {"Cut", "Engrave"}
        assert all(wp.source.source_file == ILLUSTRATOR for wp in added)
        assert sent[0]["individual"] is True

    @pytest.mark.asyncio
    async def test_a_traced_dxfs_shapes_know_their_color(
        self, doc_editor, task_mgr, bed
    ):
        """The outline red, the 120 dots black, all on layer 0."""
        options = ImportOptions(grouping=ImportGrouping.INDIVIDUAL)

        added = await _import(doc_editor, task_mgr, TRACED, options=options)

        assert len(added) == 121
        outline = max(added, key=lambda wp: wp.size[0])
        assert outline.source_color == "#ff0000"
        assert {wp.source_color for wp in added if wp is not outline} == {
            "#000000"
        }
        assert {wp.source_layer for wp in added} == {"0"}


@pytest.mark.asyncio
async def test_single_keeps_one_workpiece_and_adds_the_image(
    doc_editor, task_mgr, bed
):
    options = ImportOptions()
    spec = _illustrator_spec(layer_import_mode=LayerImportMode.FLATTEN)

    single, image = await _import(
        doc_editor, task_mgr, ILLUSTRATOR, spec, options
    )

    assert _contours(single) == 7
    assert image.source_layer == "Engrave"


def _ink(wp, px_per_mm=4) -> int:
    """The opaque pixels of the workpiece rendered at its size."""
    width, height = wp.size
    surface = wp.render_to_pixels(
        round(width * px_per_mm), round(height * px_per_mm)
    )
    assert surface is not None
    pixels = np.ndarray(
        (surface.get_height(), surface.get_stride() // 4, 4),
        dtype=np.uint8,
        buffer=surface.get_data(),
    )
    return int((pixels[:, : surface.get_width(), 3] > 128).sum())


@pytest.mark.asyncio
async def test_a_kept_image_is_not_also_in_the_vector_render(
    doc_editor, task_mgr, bed, tmp_path
):
    """
    A PNG placed inside a frame: kept as an image workpiece, it is
    left out of the frame's render (an engrave of the frame would burn
    it again); imported as before, the frame's render holds it.
    """
    grey = (pyvips.Image.black(40, 20) + 128).cast("uchar")
    png = base64.b64encode(grey.pngsave_buffer()).decode()
    path = tmp_path / "framed.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="100mm" viewBox="0 0 100 100"><g id="L">'
        '<rect x="0" y="0" width="100" height="100" fill="none" '
        'stroke="#000" stroke-width="1"/><image x="20" y="30" '
        f'width="60" height="30" href="data:image/png;base64,{png}"/>'
        "</g></svg>"
    )
    (before,) = await _import(doc_editor, task_mgr, path)
    options = ImportOptions(grouping=ImportGrouping.PIECES)

    frame, image = await _import(doc_editor, task_mgr, path, options=options)

    assert frame.source_segment.vectorization_spec.images_apart
    assert image.size == pytest.approx((60, 30))
    # 60 x 30 mm of opaque image at 4 px/mm: 28800 pixels.
    assert _ink(before) - _ink(frame) > 25000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transform, kept",
    [
        ("translate(5 5)", True),
        ("rotate(30 50 45)", False),
        ("scale(-1 1) translate(-100 0)", False),
    ],
)
async def test_a_turned_or_flipped_image_is_skipped(
    doc_editor, task_mgr, bed, tmp_path, transform, kept
):
    grey = (pyvips.Image.black(40, 20) + 128).cast("uchar")
    png = base64.b64encode(grey.pngsave_buffer()).decode()
    path = tmp_path / "photo.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" '
        'height="100mm" viewBox="0 0 100 100"><g id="L">'
        '<rect x="0" y="0" width="100" height="100" fill="none" '
        'stroke="#000"/><image id="Photo" x="20" y="30" width="60" '
        f'height="30" transform="{transform}" '
        f'href="data:image/png;base64,{png}"/></g></svg>'
    )
    tree = SvgImporter(path.read_bytes(), path).build_tree()

    added = await _import(doc_editor, task_mgr, path, options=BY_SOURCE)

    (image,) = tree.root.images()
    assert image_is_placeable(image) is kept
    assert skipped_image_warnings(tree) == (
        []
        if kept
        else [
            'Image "Photo" is rotated, skewed or flipped and was not imported.'
        ]
    )
    assert len(added) == (2 if kept else 1)


@pytest.mark.asyncio
async def test_by_source_keeps_the_ppi_of_a_unitless_file(
    doc_editor, task_mgr, bed, tmp_path
):
    """A 144 x 72 unit rect at 72 ppi is 2 x 1 inches."""
    path = tmp_path / "unitless.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
        '<g id="L"><rect x="10" y="10" width="144" height="72" '
        'fill="none" stroke="red"/></g></svg>'
    )
    spec = PassthroughSpec(ppi=72)

    (piece,) = await _import(doc_editor, task_mgr, path, spec, BY_SOURCE)

    assert piece.size == pytest.approx((50.8, 25.4))


# Illustrator's export of a one-layer file: the layer's content straight
# under the root, a named group ("Logo") beside a frame and an unnamed
# group.
ONE_LAYER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<svg id="Layer_1" data-name="Layer 1" '
    'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
    "<defs><style>.cls-1{fill:none;stroke:#ff0000;}</style></defs>"
    '<rect class="cls-1" x="10" y="10" width="180" height="80"/>'
    '<g id="Logo"><circle cx="50" cy="50" r="10"/>'
    '<circle cx="80" cy="50" r="10"/></g>'
    '<g><rect x="120" y="40" width="20" height="20"/></g></svg>'
)


class TestShapesBesideNamedGroups:
    """
    A file with shapes beside its named groups has no layers: nothing
    is dropped, and its groups are groups.
    """

    @pytest.fixture
    def path(self, tmp_path):
        path = tmp_path / "one_layer.svg"
        path.write_text(ONE_LAYER)
        return path

    def test_the_dialog_lists_no_layers(self, path):
        manifest = SvgImporter(path.read_bytes(), path).scan()

        assert manifest.layers == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode", [LayerImportMode.FLATTEN, LayerImportMode.NEW_LAYERS]
    )
    async def test_a_single_shape_keeps_every_shape(
        self, doc_editor, task_mgr, bed, path, mode
    ):
        layers = list(doc_editor.doc.layers)
        spec = PassthroughSpec(layer_import_mode=mode)

        (single,) = await _import(doc_editor, task_mgr, path, spec)

        assert _contours(single) == 4
        assert single.source_segment.layer_id is None
        assert doc_editor.doc.layers == layers

    @pytest.mark.asyncio
    async def test_by_source_makes_a_piece_of_each_group(
        self, doc_editor, task_mgr, bed, path
    ):
        """Logo (2 circles), the unnamed group's rect, the frame."""
        added = await _import(doc_editor, task_mgr, path, options=BY_SOURCE)

        assert sorted(_contours(wp) for wp in added) == [1, 1, 2]
        frame = max(added, key=lambda wp: wp.size[0])
        assert frame.source_color == "#ff0000"
        assert {wp.source_layer for wp in added} == {None}


class TestTracedArtwork:
    def test_a_traced_dxf_looks_traced_a_cad_drawing_not(self):
        """
        illustrator_traced.dxf: 121 closed paths, median 2.25 mm2;
        cad_plate.dxf: 9; the Illustrator SVG: 6.
        """
        traced = DxfImporter(TRACED.read_bytes(), TRACED).build_tree()
        plates = DxfImporter(PLATES.read_bytes(), PLATES).build_tree()
        svg = SvgImporter(ILLUSTRATOR.read_bytes(), ILLUSTRATOR).build_tree()

        assert looks_traced(DxfImporter, traced)
        assert not looks_traced(DxfImporter, plates)
        assert not looks_traced(SvgImporter, svg)

    def test_only_a_dxf_is_asked(self):
        traced = DxfImporter(TRACED.read_bytes(), TRACED).build_tree()

        assert not looks_traced(SvgImporter, traced)
        assert not looks_traced(DxfImporter, None)

    def test_large_shapes_are_not_traced_artwork(self):
        """The same 121 paths, each 10 times larger: median 225 mm2."""
        traced = DxfImporter(TRACED.read_bytes(), TRACED).build_tree()
        traced.unit_to_mm = 10.0

        assert not looks_traced(DxfImporter, traced)


@pytest.fixture
def recipe_mgr(doc_editor, tmp_path, monkeypatch):
    """A RecipeManager on a private directory, used by the context."""
    mgr = RecipeManager(tmp_path / "recipes")
    monkeypatch.setattr(doc_editor.context, "_recipe_mgr", mgr)
    return mgr


def _stock(doc, material_uid, thickness):
    """Puts a stock of a material and thickness in the document."""
    asset = StockAsset()
    asset.material_uid = material_uid
    asset.thickness = thickness
    doc.add_asset(asset)
    doc.add_child(StockItem(stock_asset_uid=asset.uid))


INTERIOR = ImportOptions(
    grouping=ImportGrouping.PIECES, interior_on_own_layer=True
)


class TestInteriorLayer:
    @pytest.mark.asyncio
    async def test_engraves_by_the_recipe_for_the_machine_and_material(
        self, doc_editor, task_mgr, bed, recipe_mgr
    ):
        """
        The interior layer gets one Engrave step, set by the recipe
        made for the active machine, the stock's material and Engrave;
        the color the recipe gives the layer is part of the import's
        one undo step.
        """
        _stock(doc_editor.doc, "mdf", 3.0)
        recipe = Recipe(
            name="MDF engrave",
            color="#3366ff",
            target_step_types=["EngraveStep"],
            target_machine_id=bed.id,
            material_uid="mdf",
            settings={"power": 0.25, "cut_speed": 18000},
        )
        recipe_mgr.add_recipe(recipe)
        history = doc_editor.history_manager
        entries = len(history.undo_stack)

        await _import(doc_editor, task_mgr, TRACED, options=INTERIOR)

        engrave = doc_editor.doc.layers[-1]
        assert engrave.name == "illustrator_traced engrave"
        (step,) = engrave.workflow.steps
        assert type(step).__name__ == "EngraveStep"
        assert step.applied_recipe_uid == recipe.uid
        assert (step.power, step.cut_speed) == (0.25, 18000)
        assert engrave.color == "#3366ff"
        assert len(history.undo_stack) == entries + 1

        history.undo()

        assert engrave not in doc_editor.doc.layers

    @pytest.mark.asyncio
    async def test_engraves_by_the_step_defaults_without_a_recipe(
        self, doc_editor, task_mgr, bed, recipe_mgr, engrave_step_class
    ):
        """
        No recipe matches (the one here is for another material): the
        Engrave step keeps its own defaults.
        """
        _stock(doc_editor.doc, "mdf", 3.0)
        recipe_mgr.add_recipe(
            Recipe(
                name="Acrylic engrave",
                target_step_types=["EngraveStep"],
                material_uid="acrylic",
                settings={"power": 0.25, "cut_speed": 18000},
            )
        )
        defaults = engrave_step_class.create(doc_editor.context)

        await _import(doc_editor, task_mgr, TRACED, options=INTERIOR)

        (step,) = doc_editor.doc.layers[-1].workflow.steps
        assert type(step) is engrave_step_class
        assert step.applied_recipe_uid is None
        assert (step.power, step.cut_speed) == (
            defaults.power,
            defaults.cut_speed,
        )

    @pytest.mark.asyncio
    async def test_only_an_import_with_interior_pieces_makes_it(
        self, doc_editor, task_mgr, bed
    ):
        """cad_plate.dxf's holes are boundary (cut), not interior."""
        layers = list(doc_editor.doc.layers)

        await _import(doc_editor, task_mgr, PLATES, options=INTERIOR)

        assert doc_editor.doc.layers == layers
