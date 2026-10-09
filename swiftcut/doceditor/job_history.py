"""
The last jobs run on each machine: what ran, with which settings, and
a copy of the document to load or run again.

Each machine has a folder under the history root, named after the
machine (its id is a per-install uuid; its name is what the lab knows
it by), holding one folder per job:

    <name>-<hash>/<UTC time>/entry.yaml    what ran (HISTORY_VERSION)
                             project.ryp   the document, as saved
                             thumb.png     the job's ops, <= 200 px

<name> is the machine name made safe for a folder, which can make two
names one ("ilab 614", "ilab_614"); <hash> is the start of the exact
name's SHA-256, which keeps them apart.
"""

import hashlib
import io
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cairo
import numpy as np
import yaml
from blinker import Signal
from raygeo.ops import Ops
from raygeo.ops.convert import ViewSpec
from raygeo.ops.convert.view import render_ops

from .file_cmd import write_project

if TYPE_CHECKING:
    from ..core.doc import Doc

logger = logging.getLogger(__name__)

HISTORY_VERSION = 1
# Jobs kept per machine; the oldest goes when a new one is recorded.
KEEP_PER_MACHINE = 10
# The thumbnail's longer side, in pixels.
THUMBNAIL_PX = 200

ENTRY_FILE = "entry.yaml"
PROJECT_FILE = "project.ryp"
THUMBNAIL_FILE = "thumb.png"

# Pre-multiplied BGRA, as raygeo renders: a mid grey that reads on a
# light and a dark window alike. Cuts are solid; engraving fades with
# its power, as it burns.
_INK = 140
_CLEAR = [0, 0, 0, 0]
_CUT_LUT = [_CLEAR] + [[_INK, _INK, _INK, 255]] * 255
_ENGRAVE_LUT = [[round(_INK * i / 255)] * 3 + [i] for i in range(256)]


@dataclass
class JobHistoryEntry:
    """One job as the history recorded it."""

    path: Path
    date: datetime
    machine: str
    document: str
    duration_s: float
    estimate_s: float | None
    stopped: bool
    layers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def project_path(self) -> Path:
        return self.path / PROJECT_FILE

    @property
    def thumbnail_path(self) -> Path | None:
        path = self.path / THUMBNAIL_FILE
        return path if path.exists() else None

    @classmethod
    def load(cls, path: Path) -> "JobHistoryEntry":
        """
        Reads a job's entry.yaml. Raises for one that is not an entry,
        or holds a name, layer or step the history window cannot show.
        """
        data = yaml.safe_load((path / ENTRY_FILE).read_text("utf-8"))
        if not isinstance(data, dict):
            raise TypeError(f"{ENTRY_FILE} holds no entry")
        machine, document = data["machine"], data["document"]
        if not (isinstance(machine, str) and isinstance(document, str)):
            raise TypeError(f"not names: {machine!r}, {document!r}")
        return cls(
            path=path,
            date=datetime.fromisoformat(data["date"]),
            machine=machine,
            document=document,
            duration_s=float(data["duration_s"]),
            estimate_s=data.get("estimate_s"),
            stopped=bool(data.get("stopped", False)),
            layers=_checked_layers(data.get("layers") or []),
        )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _checked_layers(layers: Any) -> list[dict[str, Any]]:
    """
    An entry's layers, each with a name and steps, each step with its
    type and speed, and power, min power and passes only as numbers.
    """
    if not isinstance(layers, list):
        raise TypeError(f"layers is not a list: {layers!r}")
    for layer in layers:
        if not (
            isinstance(layer, dict)
            and isinstance(layer.get("name"), str)
            and isinstance(layer.get("steps"), list)
        ):
            raise TypeError(f"not a layer: {layer!r}")
        for step in layer["steps"]:
            if not (
                isinstance(step, dict)
                and isinstance(step.get("type"), str)
                and _is_number(step.get("speed"))
                and all(
                    _is_number(step[key])
                    for key in ("power", "min_power")
                    if key in step
                )
                and ("passes" not in step or type(step["passes"]) is int)
            ):
                raise TypeError(f"not a step: {step!r}")
    return layers


def job_layers(doc: "Doc") -> list[dict[str, Any]]:
    """
    The layers a job runs and each step's settings.

    Visible layers with workpieces, and their visible steps: the step
    type, speed in the model's unit (mm/min), power and min power
    (0-1) and passes, where the step has them.
    """
    layers = []
    for layer in doc.layers:
        workflow = layer.workflow
        if not layer.visible or workflow is None:
            continue
        if not layer.all_workpieces:
            continue
        steps = []
        for step in workflow.steps:
            if not step.visible:
                continue
            settings: dict[str, Any] = {
                "type": step.typelabel,
                "speed": step.cut_speed,
            }
            for key in ("power", "min_power"):
                value = getattr(step, key, None)
                if value is not None:
                    settings[key] = float(value)
            for transformer in step.per_step_transformers_dicts:
                if (
                    transformer.get("name") == "MultiPassTransformer"
                    and transformer.get("enabled", True)
                ):
                    settings["passes"] = int(transformer["passes"])
            steps.append(settings)
        if steps:
            layers.append({"name": layer.name, "steps": steps})
    return layers


def render_thumbnail(ops: Ops, max_px: int = THUMBNAIL_PX) -> bytes | None:
    """
    The job's cuts and engraving as a PNG, its longer side at most
    max_px. Travel is left out. None for a job that draws nothing.
    """
    if ops.is_empty():
        return None
    min_x, min_y, max_x, max_y = ops.rect()
    longest = max(max_x - min_x, max_y - min_y)
    if longest <= 0:
        return None
    margin_px = 2
    ppm = (max_px - 2 * margin_px) / longest
    pad = margin_px / ppm
    spec = ViewSpec(
        pixels_per_mm=(ppm, ppm),
        render_bbox=(min_x - pad, min_y - pad, max_x + pad, max_y + pad),
        cut_color=_CUT_LUT[-1],
        travel_color=_CLEAR,
        zero_power_color=_CLEAR,
        cut_lut=_CUT_LUT,
        engrave_lut=_ENGRAVE_LUT,
        show_travel_moves=False,
        max_dimension_px=max_px,
    )
    result = render_ops(ops, spec)
    if result is None:
        return None
    bitmap = np.array(result.bitmap, dtype=np.uint8)
    height, width = bitmap.shape[:2]
    surface = cairo.ImageSurface.create_for_data(
        memoryview(bitmap), cairo.FORMAT_ARGB32, width, height, width * 4
    )
    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    return buffer.getvalue()


def _folder_name(machine: str) -> str:
    """A machine name as a folder name, one per name."""
    name = re.sub(r"[^\w.-]+", "_", machine).strip("._") or "machine"
    digest = hashlib.sha256(machine.encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


class JobHistory:
    """The job history under one root folder, kept per machine."""

    def __init__(self, root: Path, keep: int = KEEP_PER_MACHINE):
        self.root = root
        self.keep = keep
        # Sent with machine= after a job is recorded.
        self.changed = Signal()

    def _machine_dir(self, machine: str) -> Path:
        return self.root / _folder_name(machine)

    def record(
        self,
        *,
        machine: str,
        document: str,
        project: str,
        layers: list[dict[str, Any]],
        duration_s: float,
        estimate_s: float | None,
        stopped: bool,
        thumbnail: bytes | None,
        when: datetime | None = None,
    ) -> JobHistoryEntry:
        """
        Records a job, then drops the machine's oldest beyond keep.

        project is the document's project.json text, taken when the
        job started. entry.yaml is written last, and whole: to a
        temporary file first, then renamed. A folder without one is a
        job that was never fully recorded.
        """
        when = when or datetime.now(timezone.utc)
        path = self._machine_dir(machine) / when.astimezone(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%S%fZ")
        path.mkdir(parents=True)
        write_project(path / PROJECT_FILE, project)
        if thumbnail:
            (path / THUMBNAIL_FILE).write_bytes(thumbnail)
        entry = JobHistoryEntry(
            path=path,
            date=when.astimezone(),
            machine=machine,
            document=document,
            duration_s=round(duration_s, 1),
            estimate_s=(
                None if estimate_s is None else round(estimate_s, 1)
            ),
            stopped=stopped,
            layers=layers,
        )
        data = {
            "version": HISTORY_VERSION,
            "date": entry.date.isoformat(timespec="seconds"),
            "machine": entry.machine,
            "document": entry.document,
            "duration_s": entry.duration_s,
            "estimate_s": entry.estimate_s,
            "stopped": entry.stopped,
            "layers": entry.layers,
        }
        partial = path / f"{ENTRY_FILE}.part"
        partial.write_text(yaml.safe_dump(data, sort_keys=False), "utf-8")
        os.replace(partial, path / ENTRY_FILE)
        logger.info(f"Job recorded in the history: {path}")
        self.prune(machine)
        self.changed.send(self, machine=machine)
        return entry

    def _job_dirs(self, machine: str) -> list[Path]:
        """The machine's job folders, oldest first."""
        machine_dir = self._machine_dir(machine)
        if not machine_dir.is_dir():
            return []
        return sorted(p for p in machine_dir.iterdir() if p.is_dir())

    def entries(self, machine: str) -> list[JobHistoryEntry]:
        """The machine's recorded jobs, newest first."""
        entries = []
        for path in reversed(self._job_dirs(machine)):
            try:
                entries.append(JobHistoryEntry.load(path))
            except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
                logger.warning(f"Skipping an unreadable job entry: {path}")
        return entries

    def prune(self, machine: str) -> None:
        """Keeps only the machine's newest keep jobs."""
        dirs = self._job_dirs(machine)
        for path in dirs[: max(0, len(dirs) - self.keep)]:
            shutil.rmtree(path, ignore_errors=True)
