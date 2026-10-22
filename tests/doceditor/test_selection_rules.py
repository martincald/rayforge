"""
The selection commands' rules: Select Inside, Select Similar by color,
source layer and size, Select All on a layer, and the lasso's hit test;
on synthetic items, and on the traced DXF fixture imported for real.
"""

from typing import NamedTuple

import pytest
import pytest_asyncio
from raygeo.geo import Geometry

from swiftcut.core.doc import Doc
from swiftcut.core.group import Group
from swiftcut.core.source_asset_segment import SourceAssetSegment
from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor import selection_rules as rules
from swiftcut.doceditor.import_materializer import (
    ImportGrouping,
    ImportOptions,
)
from tests.doceditor.test_import_materializer import (
    TRACED,
    _contours,
    _import,
)


def _loop(geo, points):
    geo.move_to(*points[0])
    for point in points[1:]:
        geo.line_to(*point)
    geo.close_path()


def _square():
    geo = Geometry()
    _loop(geo, [(0, 0), (1, 0), (1, 1), (0, 1)])
    return geo


def _ring():
    """A square with a square hole in its middle half."""
    geo = _square()
    _loop(geo, [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)])
    return geo


def _line():
    geo = Geometry()
    geo.move_to(0, 0)
    geo.line_to(1, 1)
    return geo


def _piece(layer, pos, size=(4, 4), geo=None, **source):
    """A workpiece of the given world box on the layer."""
    wp = WorkPiece(name="piece")
    wp._edited_boundaries = geo if geo is not None else _square()
    wp.set_size(*size)
    wp.pos = pos
    for name, value in source.items():
        setattr(wp, name, value)
    layer.add_child(wp)
    return wp


def _group(layer, items):
    """Groups the layer's items, as the Group command does."""
    result = Group.create_from_items(items, layer)
    layer.remove_children(items)
    layer.add_child(result.new_group)
    result.new_group.add_children(items)
    for item in items:
        item.matrix = result.child_matrices[item.uid]
    return result.new_group


def _from(asset_uid):
    return SourceAssetSegment(
        source_asset_uid=asset_uid, vectorization_spec=PassthroughSpec()
    )


@pytest.fixture
def doc():
    return Doc()


@pytest.fixture
def layer(doc):
    return doc.layers[0]


class TestCandidates:
    def test_the_top_level_items_of_visible_layers(self, doc, layer):
        loose = _piece(layer, (0, 0))
        group = layer.add_child(Group())
        grouped = _piece(group, (10, 0))
        hidden = doc.layers[1]
        hidden.set_visible(False)
        _piece(hidden, (20, 0))

        assert rules.candidates(doc) == [loose, group]
        assert grouped not in rules.candidates(doc)


class TestSelectInside:
    def test_picks_the_shapes_inside_the_outline(self, doc, layer):
        plate = _piece(layer, (0, 0), (100, 100), _ring())
        inside = _piece(layer, (10, 10))
        in_the_hole = _piece(layer, (48, 48))
        outside = _piece(layer, (150, 10))
        astride = _piece(layer, (98, 10), (10, 4))

        picked = rules.select_inside([plate], rules.candidates(doc))

        assert picked == [inside, in_the_hole]
        assert plate not in picked
        assert outside not in picked
        assert astride not in picked

    def test_a_group_inside_is_picked_by_its_center(self, doc, layer):
        plate = _piece(layer, (0, 0), (100, 100))
        group = _group(
            layer, [_piece(layer, (20, 20)), _piece(layer, (60, 60))]
        )

        assert rules.select_inside([plate], rules.candidates(doc)) == [group]

    def test_open_contours_have_no_inside(self, doc, layer):
        line = _piece(layer, (0, 0), (100, 100), _line())
        _piece(layer, (40, 10))

        assert not rules.has_closed_contour(line)
        assert rules.select_inside([line], rules.candidates(doc)) == []

    def test_a_closed_contour_beside_an_open_one_counts(self, doc, layer):
        geo = _square()
        geo.move_to(0, 0)
        geo.line_to(1, 1)
        plate = _piece(layer, (0, 0), (100, 100), geo)
        inside = _piece(layer, (10, 60))

        assert rules.has_closed_contour(plate)
        assert rules.select_inside([plate], rules.candidates(doc)) == [inside]

    def test_every_reference_counts(self, doc, layer):
        left = _piece(layer, (0, 0), (50, 50))
        right = _piece(layer, (100, 0), (50, 50))
        in_left = _piece(layer, (10, 10))
        in_right = _piece(layer, (110, 10))
        _piece(layer, (70, 10))

        picked = rules.select_inside([left, right], rules.candidates(doc))

        assert picked == [in_left, in_right]

    def test_a_hidden_layers_shapes_are_never_picked(self, doc, layer):
        plate = _piece(layer, (0, 0), (100, 100))
        hidden = doc.layers[1]
        hidden.set_visible(False)
        _piece(hidden, (10, 10))

        assert rules.select_inside([plate], rules.candidates(doc)) == []


class TestSelectSimilar:
    def test_by_color(self, doc, layer):
        red = _piece(layer, (0, 0), source_color="#ff0000")
        also_red = _piece(layer, (10, 0), source_color="#ff0000")
        _piece(layer, (20, 0), source_color="#000000")
        _piece(layer, (30, 0))

        assert rules.select_similar_color(red, rules.candidates(doc)) == [
            red,
            also_red,
        ]

    def test_no_color_matches_nothing(self, doc, layer):
        unknown = _piece(layer, (0, 0))
        _piece(layer, (10, 0))

        assert rules.source_color(unknown) is None
        assert rules.select_similar_color(unknown, [unknown]) == []

    def test_a_group_takes_its_first_workpieces_color(self, doc, layer):
        black = _piece(layer, (0, 0), source_color="#000000")
        group = _group(
            layer,
            [
                _piece(layer, (20, 0), source_color="#000000"),
                _piece(layer, (30, 0), source_color="#ff0000"),
            ],
        )

        assert rules.select_similar_color(black, rules.candidates(doc)) == [
            black,
            group,
        ]

    def test_by_source_layer_in_the_same_file(self, doc, layer):
        a = _piece(layer, (0, 0), source_layer="0", source_segment=_from("A"))
        same = _piece(
            layer, (10, 0), source_layer="0", source_segment=_from("A")
        )
        _piece(layer, (20, 0), source_layer="0", source_segment=_from("B"))
        _piece(layer, (30, 0), source_layer="1", source_segment=_from("A"))
        _piece(layer, (40, 0), source_segment=_from("A"))

        assert rules.select_similar_source_layer(a, rules.candidates(doc)) == [
            a,
            same,
        ]

    def test_no_source_layer_matches_nothing(self, doc, layer):
        unknown = _piece(layer, (0, 0), source_segment=_from("A"))

        assert rules.source_layer_key(unknown) is None
        assert rules.select_similar_source_layer(unknown, [unknown]) == []

    def test_by_size_within_a_quarter_of_the_area(self, doc, layer):
        reference = _piece(layer, (0, 0), (10, 10))
        bigger_in = _piece(layer, (20, 0), (12.4, 10))
        _piece(layer, (40, 0), (12.6, 10))
        smaller_in = _piece(layer, (60, 0), (10, 7.6))
        _piece(layer, (80, 0), (10, 7.4))

        assert rules.select_similar_size(reference, rules.candidates(doc)) == [
            reference,
            bigger_in,
            smaller_in,
        ]


class TestSelectAllOnLayer:
    def test_picks_the_layers_items_only(self, doc, layer):
        first = _piece(layer, (0, 0))
        group = _group(layer, [_piece(layer, (10, 0))])
        _piece(doc.layers[1], (20, 0))

        assert rules.select_all_on_layer(first, rules.candidates(doc)) == [
            first,
            group,
        ]


class TestLassoHit:
    # A C opening to the right: its notch is x 20..60, y 20..40.
    LASSO = (
        (0, 0),
        (60, 0),
        (60, 20),
        (20, 20),
        (20, 40),
        (60, 40),
        (60, 60),
        (0, 60),
    )

    def _hit(self, item):
        return rules.point_in_polygon(rules.world_center(item), self.LASSO)

    def test_a_concave_lasso_leaves_its_notch_out(self, layer):
        bottom_arm = _piece(layer, (38, 8))
        top_arm = _piece(layer, (38, 48))
        spine = _piece(layer, (8, 28))
        in_the_notch = _piece(layer, (38, 28))
        outside = _piece(layer, (78, 28))

        assert self._hit(bottom_arm)
        assert self._hit(top_arm)
        assert self._hit(spine)
        assert not self._hit(in_the_notch)
        assert not self._hit(outside)

    def test_too_few_points_hold_nothing(self):
        assert not rules.point_in_polygon((0, 0), [(-1, -1), (1, 1)])


#: The traced DXF (make_fixtures.py): a red outline around 12 x 10 dots,
#: each a 1.5 mm square.
DOTS = 12 * 10
DOT_MM = 1.5
OUTLINE_MM = (120, 80)

INDIVIDUAL = ImportOptions(grouping=ImportGrouping.INDIVIDUAL)
ENGRAVE_PIECES = ImportOptions(
    grouping=ImportGrouping.PIECES, interior_on_own_layer=True
)


class Traced(NamedTuple):
    doc: Doc
    outline: WorkPiece
    dots: list[WorkPiece]
    decoy: WorkPiece


def _split_outline(added):
    """The imported outline and the pieces inside it."""
    outline = max(added, key=lambda wp: wp.size[0])
    return outline, [wp for wp in added if wp is not outline]


@pytest_asyncio.fixture
async def traced(doc_editor, task_mgr, test_machine_and_config):
    """
    The traced DXF imported as individual shapes on the first layer of
    a document, and a plain piece of another layer, away from them.
    """
    doc = doc_editor.doc
    assert len(doc.layers) >= 2
    added = await _import(doc_editor, task_mgr, TRACED, options=INDIVIDUAL)
    outline, dots = _split_outline(added)
    decoy = _piece(doc.layers[1], (500, 500))
    return Traced(doc, outline, dots, decoy)


class TestTracedDxf:
    def test_the_import_is_an_outline_and_its_dots(self, traced):
        assert len(traced.dots) == DOTS
        assert traced.outline.size == pytest.approx(OUTLINE_MM)
        assert all(
            wp.size == pytest.approx((DOT_MM, DOT_MM)) for wp in traced.dots
        )
        assert {wp.layer for wp in [traced.outline, *traced.dots]} == {
            traced.doc.layers[0]
        }

    def test_select_inside_the_outline_picks_the_dots(self, traced):
        picked = rules.select_inside(
            [traced.outline], rules.candidates(traced.doc)
        )

        assert len(picked) == DOTS
        assert set(picked) == set(traced.dots)
        assert traced.outline not in picked
        assert traced.decoy not in picked

    def test_similar_color_of_a_dot_is_the_dots(self, traced):
        picked = rules.select_similar_color(
            traced.dots[7], rules.candidates(traced.doc)
        )

        assert len(picked) == DOTS
        assert set(picked) == set(traced.dots)

    def test_similar_color_of_the_outline_is_the_outline(self, traced):
        picked = rules.select_similar_color(
            traced.outline, rules.candidates(traced.doc)
        )

        assert picked == [traced.outline]

    def test_similar_source_layer_of_a_dot_is_the_whole_import(self, traced):
        picked = rules.select_similar_source_layer(
            traced.dots[7], rules.candidates(traced.doc)
        )

        assert len(picked) == DOTS + 1
        assert set(picked) == {traced.outline, *traced.dots}
        assert traced.decoy not in picked

    @pytest.mark.asyncio
    async def test_a_second_import_of_the_file_is_not_the_same_layer(
        self, traced, doc_editor, task_mgr
    ):
        """Both imports name layer "0", from different source assets."""
        added = await _import(doc_editor, task_mgr, TRACED, options=INDIVIDUAL)
        assert len(added) == DOTS + 1
        assert {wp.source_layer for wp in added} == {"0"}
        _outline, dots = _split_outline(added)
        first = {traced.outline, *traced.dots}
        second = set(added)
        candidates = rules.candidates(traced.doc)

        assert len(candidates) == 2 * (DOTS + 1) + 1
        for reference, same_import in (
            (traced.dots[7], first),
            (dots[7], second),
        ):
            picked = rules.select_similar_source_layer(reference, candidates)

            assert len(picked) == DOTS + 1
            assert set(picked) == same_import

    def test_similar_size_of_a_dot_is_the_dots(self, traced):
        picked = rules.select_similar_size(
            traced.dots[7], rules.candidates(traced.doc)
        )

        assert len(picked) == DOTS
        assert set(picked) == set(traced.dots)
        assert traced.outline not in picked

    def test_similar_size_of_the_outline_is_the_outline(self, traced):
        picked = rules.select_similar_size(
            traced.outline, rules.candidates(traced.doc)
        )

        assert picked == [traced.outline]

    def test_select_all_on_the_dots_layer_leaves_the_other_out(self, traced):
        picked = rules.select_all_on_layer(
            traced.dots[7], rules.candidates(traced.doc)
        )

        assert len(picked) == DOTS + 1
        assert set(picked) == {traced.outline, *traced.dots}
        assert traced.decoy not in picked

    def test_select_all_on_the_other_layer_is_its_item(self, traced):
        picked = rules.select_all_on_layer(
            traced.decoy, rules.candidates(traced.doc)
        )

        assert picked == [traced.decoy]

    def test_a_hidden_layers_items_are_not_candidates(self, traced):
        everything = {traced.outline, *traced.dots, traced.decoy}
        assert set(rules.candidates(traced.doc)) == everything

        traced.doc.layers[1].set_visible(False)

        assert set(rules.candidates(traced.doc)) == everything - {traced.decoy}

        traced.doc.layers[1].set_visible(True)
        traced.doc.layers[0].set_visible(False)

        assert rules.candidates(traced.doc) == [traced.decoy]


class TestTracedDxfAsPieces:
    @pytest.mark.asyncio
    async def test_select_all_on_the_engrave_layer_is_the_interior(
        self, doc_editor, task_mgr, test_machine_and_config
    ):
        """
        The outline piece stays on the import layer; the dots, one
        piece of 120 contours, go to the "<stem> engrave" layer.
        """
        doc = doc_editor.doc
        layers_before = len(doc.layers)

        added = await _import(
            doc_editor, task_mgr, TRACED, options=ENGRAVE_PIECES
        )

        outline, dots = added
        (engrave,) = doc.layers[layers_before:]
        assert engrave.name == "illustrator_traced engrave"
        assert outline.layer is doc.layers[0]
        assert (_contours(outline), _contours(dots)) == (1, DOTS)
        candidates = rules.candidates(doc)

        assert rules.select_all_on_layer(dots, candidates) == [dots]
        assert rules.select_all_on_layer(outline, candidates) == [outline]
        assert rules.select_inside([outline], candidates) == [dots]
