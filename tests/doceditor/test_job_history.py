"""The job history store: what it writes per job, the thumbnail, the
ten jobs it keeps per machine, and a document restored from it equal
to the one that ran.
"""

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import cairo
import numpy as np
import pytest
import yaml
from raygeo.ops import Ops

from swiftcut.core.doc import Doc
from swiftcut.core.layer import Layer
from swiftcut.core.workpiece import WorkPiece
from swiftcut.doceditor.editor import DocEditor
from swiftcut.doceditor.file_cmd import project_json
from swiftcut.doceditor.job_history import (
    HISTORY_VERSION,
    JobHistory,
    job_layers,
    render_thumbnail,
)
from swiftcut.shared.tasker.manager import TaskManager

TWO_LAYERS = Path(__file__).parent.parent / "assets" / "twolayer.ryp"

# The document carries no timestamps: Doc.to_dict has none, so nothing
# is excluded when a restored document is compared with the one that
# ran. The job's only times are entry.yaml's date and its folder name,
# both outside the document.
TIMESTAMP_FIELDS: frozenset[str] = frozenset()

T0 = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)

# ilab-614's folder: its name, then the start of the name's SHA-256.
ON_614 = "ilab-614-503f6208"


def _without(data, fields=TIMESTAMP_FIELDS):
    """A document dict with the timestamp fields dropped, at any depth."""
    if isinstance(data, dict):
        return {
            k: _without(v, fields) for k, v in data.items() if k not in fields
        }
    if isinstance(data, list):
        return [_without(v, fields) for v in data]
    return data


def _cut_ops() -> Ops:
    ops = Ops()
    ops.set_power(1.0)
    ops.move_to(0, 0)
    ops.line_to(40, 0)
    ops.line_to(40, 20)
    return ops


def _raster_ops() -> Ops:
    """A raster-only job: scan lines and the moves between them."""
    ops = Ops()
    ops.set_power(0.5)
    for row in range(5):
        ops.move_to(0, row)
        ops.scan_to(10, row, power_values=[200] * 10)
    return ops


def _png_size_and_ink(png: bytes) -> tuple[int, int, int]:
    surface = cairo.ImageSurface.create_from_png(io.BytesIO(png))
    width, height = surface.get_width(), surface.get_height()
    pixels = np.frombuffer(surface.get_data(), dtype=np.uint8).reshape(
        height, surface.get_stride() // 4, 4
    )
    return width, height, int((pixels[:, :width, 3] > 0).sum())


def _record(history, machine="ilab-614", when=T0, **kwargs):
    fields = {
        "machine": machine,
        "document": "sign",
        "project": json.dumps({"uid": "doc"}, indent=2),
        "layers": [],
        "duration_s": 61.25,
        "estimate_s": 58.0,
        "stopped": False,
        "thumbnail": render_thumbnail(_cut_ops()),
        "when": when,
    }
    fields.update(kwargs)
    return history.record(**fields)


def test_a_job_is_written_as_entry_project_and_thumbnail(tmp_path):
    history = JobHistory(tmp_path)
    layers = [{"name": "Cut", "steps": [{"type": "Contour", "speed": 600}]}]

    entry = _record(history, layers=layers, stopped=True)

    assert entry.path.parent == tmp_path / ON_614
    data = yaml.safe_load((entry.path / "entry.yaml").read_text())
    assert data["version"] == HISTORY_VERSION == 1
    assert datetime.fromisoformat(data["date"]) == T0
    assert data["machine"] == "ilab-614"
    assert data["document"] == "sign"
    assert data["duration_s"] == 61.2
    assert data["estimate_s"] == 58.0
    assert data["stopped"] is True
    assert data["layers"] == layers
    project = zipfile.ZipFile(entry.project_path).read("project.json")
    assert json.loads(project) == {"uid": "doc"}
    assert entry.thumbnail_path == entry.path / "thumb.png"

    (listed,) = history.entries("ilab-614")
    assert listed == entry


def test_a_job_without_a_thumbnail_is_still_recorded(tmp_path):
    entry = _record(JobHistory(tmp_path), thumbnail=None)

    assert entry.thumbnail_path is None
    assert JobHistory(tmp_path).entries("ilab-614") == [entry]


@pytest.mark.parametrize(
    "ops",
    [_cut_ops(), _raster_ops()],
    ids=["vector", "raster-only"],
)
def test_thumbnails_fit_200_px_and_show_the_job(ops):
    png = render_thumbnail(ops)

    assert png is not None
    width, height, ink = _png_size_and_ink(png)
    assert max(width, height) <= 200
    assert ink > 0


def test_a_tall_job_fits_200_px_too():
    ops = Ops()
    ops.set_power(1.0)
    ops.move_to(0, 0)
    ops.line_to(0, 1300)
    ops.line_to(5, 1300)

    width, height, ink = _png_size_and_ink(render_thumbnail(ops))

    assert (width, height) <= (200, 200) and height == 200
    assert ink > 0


def test_an_empty_job_has_no_thumbnail():
    assert render_thumbnail(Ops()) is None


def test_eleven_jobs_keep_the_newest_ten_per_machine(tmp_path):
    history = JobHistory(tmp_path)
    for i in range(11):
        _record(history, when=T0 + timedelta(minutes=i), document=f"j{i}")
    for i in range(3):
        _record(history, machine="ilab-626", when=T0 + timedelta(hours=i))

    on_614 = history.entries("ilab-614")
    assert [e.document for e in on_614] == [f"j{i}" for i in range(10, 0, -1)]
    assert len(list((tmp_path / ON_614).iterdir())) == 10
    assert len(history.entries("ilab-626")) == 3


def test_a_machine_name_is_a_safe_folder(tmp_path):
    entry = _record(JobHistory(tmp_path), machine="Lab 3/big")

    assert entry.path.parent == tmp_path / "Lab_3_big-2ca49965"
    assert JobHistory(tmp_path).entries("Lab 3/big")[0].machine == (
        "Lab 3/big"
    )


def test_names_made_alike_by_the_folder_keep_their_own_jobs(tmp_path):
    """"ilab 614" and "ilab_614" both read as ilab_614 in a folder."""
    history = JobHistory(tmp_path)
    for i in range(10):
        _record(history, machine="ilab 614", when=T0 + timedelta(minutes=i))
    _record(history, machine="ilab_614", when=T0 + timedelta(hours=1))

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "ilab_614-6b6287be",
        "ilab_614-ee35d3ed",
    ]
    spaced = history.entries("ilab 614")
    assert len(spaced) == 10
    assert {e.machine for e in spaced} == {"ilab 614"}
    assert [e.machine for e in history.entries("ilab_614")] == ["ilab_614"]


def test_a_half_written_job_is_skipped(tmp_path):
    history = JobHistory(tmp_path)
    entry = _record(history)
    broken = tmp_path / ON_614 / "20991231T000000000000Z"
    broken.mkdir()

    assert history.entries("ilab-614") == [entry]


def test_an_entry_cut_short_as_it_is_written_is_never_seen(
    tmp_path, monkeypatch
):
    history = JobHistory(tmp_path)
    kept = _record(history)
    write_text = Path.write_text

    def disk_full(self, data, *args, **kwargs):
        write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", disk_full)
    with pytest.raises(OSError):
        _record(history, when=T0 + timedelta(minutes=1))
    monkeypatch.undo()

    (cut_short,) = [p for p in kept.path.parent.iterdir() if p != kept.path]
    assert not (cut_short / "entry.yaml").exists()
    assert history.entries("ilab-614") == [kept]


def _truncated(text: str) -> str:
    """Cut off inside the first step, after its type."""
    return text[: text.index("speed:")]


@pytest.mark.parametrize(
    "damage",
    [
        _truncated,
        lambda text: "an entry no more\n",
        lambda text: text.replace("speed: 600", "speed: fast"),
        lambda text: text.replace("passes: 2", "passes: two"),
        lambda text: text.replace("- name: Cut", "- title: Cut"),
        lambda text: text.replace("document: sign", "document: [sign]"),
    ],
    ids=[
        "truncated",
        "not a mapping",
        "speed not a number",
        "passes not a number",
        "layer without a name",
        "document not a name",
    ],
)
def test_a_damaged_entry_is_skipped_and_logged(tmp_path, caplog, damage):
    history = JobHistory(tmp_path)
    step = {"type": "Contour", "speed": 600, "power": 0.8, "passes": 2}
    layers = [{"name": "Cut", "steps": [step]}]
    good = _record(history, layers=layers)
    bad = _record(history, layers=layers, when=T0 + timedelta(minutes=1))
    entry_yaml = bad.path / "entry.yaml"
    text = entry_yaml.read_text()
    damaged = damage(text)
    assert damaged != text
    entry_yaml.write_text(damaged)

    with caplog.at_level("WARNING"):
        assert history.entries("ilab-614") == [good]

    assert f"Skipping an unreadable job entry: {bad.path}" in caplog.text


def test_the_job_layers_are_the_visible_steps_with_their_settings(
    context_initializer,
):
    from swiftcut.core.step import Step

    doc = Doc.from_dict(json.loads(TWO_LAYERS.read_text()))
    engrave_layer, cut_layer = doc.layers
    engrave_step = engrave_layer.workflow.steps[0]
    engrave_step.cut_speed = 6000
    engrave_step.power = 0.4
    engrave_step.min_power = 0.25
    cut_step = cut_layer.workflow.steps[0]
    for t in cut_step.per_step_transformers_dicts:
        if t["name"] == "MultiPassTransformer":
            t["passes"] = 3
    hidden = Step(typelabel="Contour")
    hidden.visible = False
    cut_layer.workflow.add_step(hidden)
    empty = Layer(name="Nothing on it")
    doc.add_layer(empty)

    assert job_layers(doc) == [
        {
            "name": "Layer 1",
            "steps": [
                {
                    "type": "Engrave (Raster)",
                    "speed": 6000,
                    "power": 0.4,
                    "min_power": 0.25,
                    "passes": 1,
                }
            ],
        },
        {
            "name": "Layer 2",
            "steps": [
                {
                    "type": "Contour",
                    "speed": 500,
                    "power": 1.0,
                    "min_power": 1.0,
                    "passes": 3,
                }
            ],
        },
    ]

    cut_layer.visible = False
    assert [layer["name"] for layer in job_layers(doc)] == ["Layer 1"]


@pytest.fixture
def editor(context_initializer):
    editor = DocEditor(MagicMock(spec=TaskManager), context_initializer)
    yield editor
    editor.cleanup()


def test_a_restored_document_is_the_one_that_ran(editor, tmp_path):
    assert editor.file.load_project_from_path(TWO_LAYERS)
    original = editor.doc.to_dict()
    entry = _record(JobHistory(tmp_path), project=project_json(editor.doc))

    # The stored project is the document, byte for byte, as File >
    # Save would write it.
    stored = zipfile.ZipFile(entry.project_path).read("project.json")
    assert stored == json.dumps(original, indent=2).encode("utf-8")

    # Loading it back, over another document, gives the same document.
    editor.set_doc(Doc())
    editor.mark_as_unsaved()
    assert editor.file.load_project_from_path(
        entry.project_path, untitled=True
    )

    restored = editor.doc.to_dict()
    assert _without(restored) == _without(original)
    # Byte-equal too, once keys are sorted: a loaded step lists its own
    # keys in another order than a built one does (Step.to_dict and
    # its extra dict; File > Open reorders them the same way).
    assert json.dumps(restored, indent=2, sort_keys=True) == json.dumps(
        original, indent=2, sort_keys=True
    )
    # An untitled, unchanged copy: a save asks where, and the history's
    # own file is never written over.
    assert editor.file_path is None
    assert editor.is_saved


def test_a_project_opened_by_path_still_keeps_its_path(editor):
    assert editor.file.load_project_from_path(TWO_LAYERS)

    assert editor.file_path == TWO_LAYERS


def test_save_writes_what_project_json_says(editor, tmp_path):
    editor.doc.active_layer.add_workpiece(WorkPiece(name="a.svg"))
    path = tmp_path / "saved.ryp"

    assert editor.file.save_project_to_path(path)

    stored = zipfile.ZipFile(path).read("project.json").decode()
    assert stored == project_json(editor.doc)


def test_a_start_right_after_a_load_waits_for_the_loaded_job(editor):
    """
    Run Again starts right after a load: the job, or the error, the
    previous document left in the pipeline is never handed out for it.
    """
    pipeline = editor.pipeline
    pipeline._last_job_handle = MagicMock(name="the previous job")
    pipeline._job_error = "the previous document's error"
    pipeline._job_handle_stale = False

    assert editor.file.load_project_from_path(TWO_LAYERS, untitled=True)
    handed = []
    pipeline.generate_job_artifact(
        lambda handle, error: handed.append((handle, error))
    )

    # It waits for the loaded document's own generation.
    assert handed == []
