"""
What an SVG shows is what it imports: through FileCmd's real import
path, in every grouping, nothing invisible comes in.

shweshwe.svg is the owner's Illustrator 30.8.2 file, byte for byte,
except its hidden photo, downscaled 8x (1059 x 783 to 132 x 98 px, 1.9
MB to 50 KB) so the repository does not carry 1.9 MB. Its Layer_1 is
a hidden layer (display:none through the CSS class st1) holding that
photo; Layer_2 holds what the student drew: a square and four circles.
"""

import logging
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from raygeo.geo import Geometry

from swiftcut.core.vectorization_spec import PassthroughSpec
from swiftcut.doceditor.import_materializer import (
    ImportGrouping,
    ImportOptions,
)
from swiftcut.image.svg.importer import SvgImporter
from swiftcut.image.svg.svg_tree import visible_svg
from swiftcut.image.svg.svgutil import SVG_NS
from tests.doceditor.test_import_materializer import _contours, _import

TESTS_DIR = Path(__file__).parent.parent
SHWESHWE = TESTS_DIR / "fixtures" / "import" / "shweshwe.svg"
LOGGER = "swiftcut.image.svg.svg_tree"

# Everything here that draws nothing, beside one visible rect (in a
# clipped group) and one visible circle: 100 mm square, a unit a mm.
INVISIBLE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" \
viewBox="0 0 100 100">
  <defs>
    <style>.hide { display: none; } .ghost { opacity: 0; }</style>
    <clipPath id="clip-in-defs"><rect x="0" y="0" width="100" \
height="100"/></clipPath>
    <rect id="defs-only" x="5" y="5" width="10" height="10" fill="red"/>
  </defs>
  <clipPath id="clip-outside-defs"><rect x="1" y="1" width="98" \
height="98"/></clipPath>
  <mask id="mask-outside-defs"><rect x="2" y="2" width="96" height="96" \
fill="white"/></mask>
  <rect id="artboard" x="0" y="0" width="100" height="100" fill="none" \
stroke="none"/>
  <rect id="transparent" x="3" y="3" width="94" height="94" \
stroke="#000" fill="none" opacity="0"/>
  <rect id="ghost-class" x="4" y="4" width="92" height="92" \
stroke="#000" class="ghost"/>
  <rect id="hidden-style" x="6" y="6" width="88" height="88" \
stroke="#000" style="display:none"/>
  <g class="hide"><rect id="hidden-class" x="7" y="7" width="86" \
height="86" stroke="#000"/></g>
  <g clip-path="url(#clip-outside-defs)">
    <rect id="visible-rect" x="20" y="20" width="30" height="30" \
fill="none" stroke="#000"/>
  </g>
  <circle id="visible-circle" cx="70" cy="70" r="10" fill="none" \
stroke="#00f"/>
</svg>
"""

# No options (as before there were any), then each grouping.
GROUPINGS = {
    "legacy": None,
    "single": ImportOptions(grouping=ImportGrouping.SINGLE),
    "individual": ImportOptions(grouping=ImportGrouping.INDIVIDUAL),
    "pieces": ImportOptions(grouping=ImportGrouping.PIECES),
    "by_source": ImportOptions(grouping=ImportGrouping.BY_SOURCE),
}


@pytest.fixture
def bed(test_machine_and_config):
    """The ilab-614 bed: 1400 x 900 mm."""
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


def _world_box(added) -> tuple[float, float, float, float]:
    geo = Geometry()
    for wp in added:
        geo.extend(wp.get_world_geometry())
    return geo.rect()


def _assert_shapes(added, path: Path, options, count: int) -> None:
    """
    Only the file's own vector workpieces (no image comes in): count
    contours in all, one workpiece each with Individual shapes.
    """
    assert all(wp.source.source_file == path for wp in added)
    assert sum(_contours(wp) for wp in added) == count
    if options is not None and options.grouping is ImportGrouping.INDIVIDUAL:
        assert len(added) == count


class TestHiddenIllustratorLayer:
    def test_the_dialog_does_not_list_it(self):
        manifest = SvgImporter(SHWESHWE.read_bytes(), SHWESHWE).scan()

        assert [layer.id for layer in manifest.layers] == ["Layer_2"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(GROUPINGS))
    async def test_only_the_visible_paths_come_in(
        self, doc_editor, task_mgr, bed, caplog, name
    ):
        caplog.set_level(logging.INFO, logger=LOGGER)
        options = GROUPINGS[name]

        added = await _import(
            doc_editor, task_mgr, SHWESHWE, PassthroughSpec(), options
        )

        _assert_shapes(added, SHWESHWE, options, 5)
        assert "Layer_1" not in {layer.name for layer in doc_editor.doc.layers}
        assert {wp.source_layer for wp in added} <= {"Layer_2", None}
        assert any(
            'skipped hidden g "Layer_1" (display:none)' in record.message
            for record in caplog.records
        )


class TestInvisibleShapes:
    @pytest.fixture
    def path(self, tmp_path):
        path = tmp_path / "invisible.svg"
        path.write_text(INVISIBLE)
        return path

    def test_the_clip_still_resolves(self):
        """
        The clipPath outside <defs> moves into the file's <defs>, under
        its id, which the clipped group still names.
        """
        root = ET.fromstring(visible_svg(INVISIBLE.encode()))
        defs = root[0]

        assert defs.tag == f"{{{SVG_NS}}}defs"
        assert [c.get("id") for c in defs][-2:] == [
            "clip-outside-defs",
            "mask-outside-defs",
        ]
        (group,) = [g for g in root if g.get("clip-path")]
        assert group.get("clip-path") == "url(#clip-outside-defs)"
        assert group[0].get("id") == "visible-rect"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(GROUPINGS))
    async def test_only_the_visible_rect_and_circle_come_in(
        self, doc_editor, task_mgr, bed, caplog, path, name
    ):
        """The rect is 20..50, the circle 60..80: 60 mm square in all."""
        caplog.set_level(logging.INFO, logger=LOGGER)
        options = GROUPINGS[name]

        added = await _import(
            doc_editor, task_mgr, path, PassthroughSpec(), options
        )

        _assert_shapes(added, path, options, 2)
        x0, y0, x1, y1 = _world_box(added)
        assert (x1 - x0, y1 - y0) == pytest.approx((60, 60), abs=0.01)
        messages = [record.message for record in caplog.records]
        assert any(
            'rect "artboard" (artboard background)' in m for m in messages
        )
