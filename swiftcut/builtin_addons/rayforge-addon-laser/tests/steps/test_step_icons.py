"""Cut, Engrave, Scan and Frame each have their own glyph.

The layer card shows a step only by its icon, so two step types that
share one cannot be told apart there.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import laser_essentials
import pytest

from swiftcut.core.step_registry import step_registry

ICONS_DIR = Path(laser_essentials.__file__).parent / "resources" / "icons"
STEP_TYPES = ["ContourStep", "EngraveStep", "ScanStep", "FrameStep"]
SVG = "{http://www.w3.org/2000/svg}"
SODIPODI = "{http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd}"


def _icon_name(step_type: str) -> str:
    step_class = step_registry.get(step_type)
    assert step_class is not None, step_type
    return step_class.ICON


def test_each_step_type_has_its_own_icon():
    names = [_icon_name(step_type) for step_type in STEP_TYPES]

    assert len(set(names)) == len(names), names


@pytest.mark.parametrize("step_type", STEP_TYPES)
def test_step_icon_ships_with_the_addon(step_type):
    path = ICONS_DIR / f"{_icon_name(step_type)}.svg"

    assert path.is_file(), path


def test_scan_icon_dashes_are_filled_shapes():
    """
    GTK recolours a symbolic icon by forcing its fill, so a stroked or
    stroke-dasharray line would not draw as dashes. Each dash is its
    own filled subpath of one path instead.
    """
    path = ICONS_DIR / "step-scan-symbolic.svg"

    assert "stroke" not in path.read_text(encoding="utf-8")
    root = ET.parse(path).getroot()
    assert root.tag == f"{SVG}svg"
    assert root.get("viewBox") == "0 0 24 24"
    paths = list(root.iter(f"{SVG}path"))
    assert len(paths) == 1
    assert paths[0].get("d").count("M") > 1


def test_scan_icon_is_drawn_like_cut():
    """
    The dashes sit in Cut's group transform. GTK 4.22 drew a symbolic
    SVG whose path had only style, d and id with its own renderer,
    which dropped that transform and left the dashes off the icon; with
    Inkscape's nodetypes on the path, as Cut has, it is drawn the way
    Cut is.
    """
    cut = ET.parse(ICONS_DIR / "step-contour-symbolic.svg").getroot()
    scan = ET.parse(ICONS_DIR / "step-scan-symbolic.svg").getroot()

    assert scan.find(f"{SVG}g").get("transform") == (
        cut.find(f"{SVG}g").get("transform")
    )
    assert scan.find(f"{SVG}g/{SVG}path").get(f"{SODIPODI}nodetypes")
