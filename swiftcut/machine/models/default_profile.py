"""Bundled default machine profile for the shop's ilab-614 Ruida machine.

``ILAB_614_PROFILE`` is read from ``resources/profiles/ilab-614.yaml``,
a verbatim copy of the canonical profile committed at
``docs/profiles/ilab-614.yaml`` (tuned on the shop's Windows machine).
``MachineManager.create_default_machine`` uses it to seed a fresh
install so the app comes up already configured for this machine,
instead of a bare 200x200mm placeholder.

The file uses the same ``machine:``-wrapper shape that
``Machine.to_dict``/``Machine.from_dict`` read and write, so it is
loaded exactly like any other saved machine file.
"""

from pathlib import Path
from typing import Any

import yaml

PROFILE_FILE = (
    Path(__file__).parents[2] / "resources" / "profiles" / "ilab-614.yaml"
)

with open(PROFILE_FILE, encoding="utf-8") as _f:
    ILAB_614_PROFILE: dict[str, Any] = yaml.safe_load(_f)
