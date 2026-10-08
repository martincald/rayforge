"""Bundled machine profiles for the shop's two Ruida machines.

``ILAB_614_PROFILE`` is read from ``resources/profiles/ilab-614.yaml``,
a verbatim copy of the canonical profile committed at
``docs/profiles/ilab-614.yaml`` (tuned on the shop's Windows machine).
``ILAB_626_PROFILE`` is the same machine with a 900x900mm bed, read
from ``resources/profiles/ilab-626.yaml`` (a verbatim copy of
``docs/profiles/ilab-626.yaml``); it carries a fixed machine ``id``.
``MachineManager.ensure_default_machine`` seeds them so the app comes
up already configured for these machines, instead of a bare 200x200mm
placeholder.

The files use the same ``machine:``-wrapper shape that
``Machine.to_dict``/``Machine.from_dict`` read and write, so they are
loaded exactly like any other saved machine file.
"""

from pathlib import Path
from typing import Any

import yaml

PROFILES_DIR = Path(__file__).parents[2] / "resources" / "profiles"
PROFILE_FILE = PROFILES_DIR / "ilab-614.yaml"
ILAB_626_PROFILE_FILE = PROFILES_DIR / "ilab-626.yaml"


def _load(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


ILAB_614_PROFILE: dict[str, Any] = _load(PROFILE_FILE)
ILAB_626_PROFILE: dict[str, Any] = _load(ILAB_626_PROFILE_FILE)

# The bundled profiles, in the order the machine switcher lists them.
BUNDLED_PROFILES = (ILAB_614_PROFILE, ILAB_626_PROFILE)
BUNDLED_NAMES = tuple(p["machine"]["name"] for p in BUNDLED_PROFILES)
