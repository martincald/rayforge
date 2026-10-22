"""
What Single shape and Individual shapes put in the document today,
through FileCmd's real import path, pinned file by file: the layers,
each layer's workpieces in order (name, matrix, normalized boundaries
box and contour count, segment layer id and crop window) and the
items_imported signal. A change to the import path must leave them as
they are.

The expected values are in import_golden.json beside this file. To
record them again (only on purpose, at a commit whose output is the
reference)::

    IMPORT_GOLDEN_WRITE=1 python -m pytest tests/doceditor/\
test_import_golden.py
"""

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from swiftcut.core.vectorization_spec import (
    LayerImportMode,
    PassthroughSpec,
)

TESTS_DIR = Path(__file__).parent.parent
GOLDEN = Path(__file__).parent / "import_golden.json"
WRITE = os.environ.get("IMPORT_GOLDEN_WRITE") == "1"

FILES = [
    "image/svg/twolayer.svg",
    "image/svg/nested-rect.svg",
    "image/svg/multicolor.svg",
    "image/dxf/circle.dxf",
    "image/dxf/acdbarc.dxf",
    "image/dxf/acdbcircle.dxf",
    "image/dxf/3mm2x.dxf",
    "perf/many_shapes.dxf",
]

SPECS = {
    "new_layers": lambda: PassthroughSpec(
        layer_import_mode=LayerImportMode.NEW_LAYERS
    ),
    "flatten": lambda: PassthroughSpec(
        layer_import_mode=LayerImportMode.FLATTEN
    ),
    "default": PassthroughSpec,
}


def _r(value: float) -> float:
    return round(value, 6) + 0.0


def _rs(values) -> list[float]:
    return [_r(v) for v in values]


def _workpiece_record(wp) -> list:
    """One workpiece as the golden file holds it."""
    boundaries = wp.boundaries
    segment = wp.source_segment
    crop = segment.crop_window_px if segment else None
    return [
        wp.name,
        _rs(v for row in wp.matrix.to_list() for v in row),
        _rs(boundaries.rect()) if boundaries else None,
        len(boundaries.split_into_contours()) if boundaries else 0,
        segment.layer_id if segment else None,
        _rs(crop) if crop else None,
    ]


def _doc_record(doc, sent) -> dict:
    """The document's layers and workpieces, and what was announced."""
    return {
        "layers": [
            {
                "name": layer.name,
                "workpieces": [
                    _workpiece_record(wp) for wp in layer.all_workpieces
                ],
            }
            for layer in doc.layers
        ],
        "signal": [
            [len(kwargs["items"]), kwargs["individual"]] for kwargs in sent
        ],
    }


async def _wait_for_import(editor, task_mgr, timeout=60.0):
    """Waits until the import task and the pipeline are done."""
    deadline = time.monotonic() + timeout
    while task_mgr.has_tasks():
        assert time.monotonic() < deadline, "import did not finish"
        await asyncio.sleep(0.01)
    await editor.wait_until_settled()


def _assert_matches(actual, expected, where="") -> None:
    """Equal, numbers within 1e-6."""
    if isinstance(expected, float) or isinstance(actual, float):
        assert actual == pytest.approx(expected, abs=1e-6), where
    elif isinstance(expected, list):
        assert isinstance(actual, list), where
        assert len(actual) == len(expected), f"{where}: length"
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _assert_matches(a, e, f"{where}[{i}]")
    elif isinstance(expected, dict):
        assert sorted(actual) == sorted(expected), where
        for key in expected:
            _assert_matches(actual[key], expected[key], f"{where}.{key}")
    else:
        assert actual == expected, where


@pytest.fixture
def bed(test_machine_and_config):
    """The ilab-614 bed: 1400 x 900 mm."""
    machine, _config = test_machine_and_config
    machine.set_axis_extents(1400, 900)
    return machine


@pytest.mark.asyncio
@pytest.mark.parametrize("split_paths", [False, True], ids=["single", "ind"])
@pytest.mark.parametrize("spec_name", list(SPECS))
@pytest.mark.parametrize("file", FILES)
async def test_import_is_unchanged(
    doc_editor, task_mgr, bed, file, spec_name, split_paths
):
    sent = []
    doc_editor.file.items_imported.connect(
        lambda sender, **kwargs: sent.append(kwargs), weak=False
    )

    doc_editor.file.load_file_from_path(
        TESTS_DIR / file,
        None,
        SPECS[spec_name](),
        split_paths=split_paths,
    )
    await _wait_for_import(doc_editor, task_mgr)

    key = f"{file}|{spec_name}|{'individual' if split_paths else 'single'}"
    actual = _doc_record(doc_editor.doc, sent)
    if WRITE:
        golden = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        golden[key] = actual
        lines = [
            f"{json.dumps(k)}:{json.dumps(golden[k], separators=(',', ':'))}"
            for k in sorted(golden)
        ]
        GOLDEN.write_text("{\n" + ",\n".join(lines) + "\n}\n")
        return
    expected = json.loads(GOLDEN.read_text())[key]
    _assert_matches(actual, expected, key)
