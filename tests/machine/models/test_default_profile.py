"""
Tests for the bundled ilab-614 default machine profile (Package B).

A fresh install seeds a single machine profile named "ilab-614", built
from the shop's real Duplotech-1490 Ruida machine, instead of a bare
200x200mm placeholder. See docs/profiles/ilab-614.source.yaml for the
verbatim source this profile was captured from.
"""

import copy
import hashlib
from pathlib import Path

import pytest
import yaml
from raygeo.ops.axis import Axis

from swiftcut.machine.models.default_profile import ILAB_614_PROFILE
from swiftcut.machine.models.machine import Origin, StartCorner
from swiftcut.machine.models.manager import MachineManager

SOURCE_YAML = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "profiles"
    / "ilab-614.source.yaml"
)


@pytest.mark.usefixtures("lite_context")
class TestIlab614DefaultProfile:
    """An empty config dir is silently seeded with the ilab-614 profile."""

    def test_empty_config_dir_seeds_ilab_614(self, lite_context):
        machines = list(lite_context.machine_mgr.machines.values())
        assert len(machines) == 1
        machine = machines[0]

        assert machine.name == "ilab-614"
        assert machine.driver_name == "RuidaDriver"
        assert machine.driver_args == {
            "host": "192.168.1.100",
            "port": 50200,
            "jog_port": 50207,
        }
        assert machine.axis_extents == (1400.0, 900.0)
        assert machine.origin == Origin.TOP_LEFT
        assert machine.start_corner == StartCorner.BOTTOM_LEFT
        assert machine.max_cut_speed == 9342
        assert machine.max_travel_speed == 3000
        assert machine.acceleration == 1000

        # Additional fields, read from docs/profiles/ilab-614.source.yaml.
        assert machine.auto_connect is True
        assert machine.arc_tolerance == 0.03
        assert machine.active_wcs == "REF0"
        z_axis = machine.axes.get(Axis.Z)
        assert z_axis is not None
        assert z_axis.extents == (-50, 50)

        # Laser head power is stored 0-100 in YAML but 0-1 in memory.
        head = machine.heads[0]
        assert head.focus_power_percent == 0.2

    def test_preexisting_profile_dir_is_untouched(self, tmp_path):
        """
        A pre-existing machine directory must be left byte-identical by
        launch/config-load: create_default_machine() must not run, and
        no file may be rewritten or added.
        """
        machine_dir = tmp_path / "pre_existing_machines"
        machine_dir.mkdir()
        existing_file = (
            machine_dir / "20fb2d0b-9637-4761-9331-286479d6307a.yaml"
        )
        existing_file.write_bytes(SOURCE_YAML.read_bytes())

        before_hash = hashlib.sha256(existing_file.read_bytes()).hexdigest()

        # This mirrors the exact "silent seed on empty dir" gate used by
        # both RayforgeContext.machine_mgr and initialize_lite_context.
        manager = MachineManager(machine_dir)
        if not manager.machines:
            manager.create_default_machine()

        after_hash = hashlib.sha256(existing_file.read_bytes()).hexdigest()

        assert after_hash == before_hash
        assert len(manager.machines) == 1
        assert list(machine_dir.glob("*.yaml")) == [existing_file]

    def test_embedded_profile_matches_source_except_name(self):
        """
        The embedded ILAB_614_PROFILE must be identical to the captured
        source YAML in every field except "name".
        """
        with open(SOURCE_YAML) as f:
            source = yaml.safe_load(f)

        embedded = copy.deepcopy(ILAB_614_PROFILE)

        source_name = source["machine"].pop("name")
        embedded_name = embedded["machine"].pop("name")

        assert source_name == "Ilab"
        assert embedded_name == "ilab-614"
        assert embedded == source
