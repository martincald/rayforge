"""
A sketch's expressions come from files: a .rfs a student imports, or a
project they open. Evaluating one must never run code
(REVIEW-0.1.1 F-05).
"""

import json
from pathlib import Path

import pytest
from sketcher.core import Sketch
from sketcher.image.importer import SketchImporter

from swiftcut.core.doc import Doc


def _escapes(marker: Path) -> list[str]:
    """Expressions that, under eval alone, create the marker file."""
    system = (
        "[c for c in ().__class__.__base__.__subclasses__() "
        "if c.__name__ == '_wrap_close'][0].__init__.__globals__"
        f"['system']('touch {marker}')"
    )
    return [
        system + " + 1",
        f"(lambda: {system})() + 1",
        (
            "(x for x in []).gi_frame.f_globals['__builtins__']['open']"
            f"('{marker}', 'w').close() or 1"
        ),
    ]


def _crafted_sketch(expression: str) -> dict:
    """A rectangle whose width parameter is the given expression."""
    sketch = Sketch(name="crafted")
    p0 = sketch.origin_id
    p1 = sketch.add_point(100, 0)
    sketch.add_line(p0, p1)
    sketch.constrain_distance(p0, p1, "width")
    sketch.set_param("width", 40)
    sketch.solve()
    data = sketch.to_dict()
    data["params"]["expressions"]["width"] = expression
    return data


@pytest.mark.parametrize("index", range(3))
def test_importing_a_crafted_sketch_file_runs_nothing(tmp_path, index):
    marker = tmp_path / "marker"
    data = _crafted_sketch(_escapes(marker)[index])

    importer = SketchImporter(
        json.dumps(data).encode("utf-8"), Path("crafted.rfs")
    )
    importer.parse()

    assert not marker.exists()


@pytest.mark.parametrize("index", range(3))
def test_opening_a_project_with_a_crafted_sketch_runs_nothing(tmp_path, index):
    marker = tmp_path / "marker"
    sketch = Sketch.from_dict(_crafted_sketch(_escapes(marker)[index]))
    doc = Doc()
    doc.add_asset(sketch)

    loaded = Doc.from_dict(doc.to_dict())
    (reloaded,) = [a for a in loaded.assets.values() if a.uid == sketch.uid]
    reloaded.get_geometry()

    assert not marker.exists()


def test_formulas_in_a_file_still_evaluate():
    sketch = Sketch.from_dict(_crafted_sketch("sqrt(1600) + floor(0.5)"))

    sketch.solve()

    assert sketch.params.get("width") == 40.0
