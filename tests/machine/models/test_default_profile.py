"""
Tests for the bundled ilab-614 default machine profile (Package B).

A fresh install seeds a single machine profile named "ilab-614", built
from the shop's real Duplotech-1490 Ruida machine, instead of a bare
200x200mm placeholder. See docs/profiles/ilab-614.yaml for the
canonical profile it embeds verbatim.
"""

import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from raygeo.ops.axis import Axis

from swiftcut.machine.driver import get_driver_cls
from swiftcut.machine.driver.ruida.ruida_driver import RuidaDriver
from swiftcut.machine.models.default_profile import (
    ILAB_614_PROFILE,
    PROFILE_FILE,
)
from swiftcut.machine.models.machine import Machine, Origin, StartCorner
from swiftcut.machine.models.manager import MachineManager

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE_YAML = REPO_ROOT / "docs" / "profiles" / "ilab-614.yaml"


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
        assert machine.start_corner == StartCorner.TOP_LEFT
        assert machine.max_cut_speed == 18000
        assert machine.max_travel_speed == 3000
        assert machine.acceleration == 1000

        # Additional fields, read from docs/profiles/ilab-614.yaml.
        assert machine.auto_connect is True
        assert machine.arc_tolerance == 0.03
        assert machine.active_wcs == "REF0"
        z_axis = machine.axes.get(Axis.Z)
        assert z_axis is not None
        assert z_axis.extents == (-50, 50)
        assert machine.cut_scale_speed_mm_s == 20.0
        assert machine.cut_scale_power_pct == 30.0

        # Laser head power is stored 0-100 in YAML but 0-1 in memory.
        head = machine.heads[0]
        assert head.focus_power_percent == 0.2

    def test_ilab_614_driver_name_resolves_to_ruida_driver(
        self, lite_context
    ):
        """
        The profile's declared driver must actually resolve to
        RuidaDriver via the driver registry, not silently fall back
        to the no-device driver.
        """
        machine = next(iter(lite_context.machine_mgr.machines.values()))

        assert get_driver_cls(machine.driver_name) is RuidaDriver

    def test_bundled_default_matches_the_live_ilab_614_endpoints(self):
        """
        The bundled default's host/ports must equal the live ilab-614
        values: 192.168.1.100 / 50200 / 50207 / 40200. Read directly
        from ILAB_614_PROFILE (not through the manager), and tied to
        RuidaDriver.RESPONSE_PORT, since the response port is a driver
        constant rather than a driver_args entry -- so the profile
        must not override it.
        """
        driver_args = ILAB_614_PROFILE["machine"]["driver_args"]

        assert driver_args == {
            "host": "192.168.1.100",
            "port": 50200,
            "jog_port": 50207,
        }
        assert "response_port" not in driver_args
        assert RuidaDriver.RESPONSE_PORT == 40200

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
        existing_file.write_bytes(PROFILE_YAML.read_bytes())

        before_hash = hashlib.sha256(existing_file.read_bytes()).hexdigest()

        # The same seed gate RayforgeContext.machine_mgr and
        # initialize_lite_context run.
        manager = MachineManager(machine_dir)
        assert manager.ensure_default_machine() is None

        after_hash = hashlib.sha256(existing_file.read_bytes()).hexdigest()

        assert after_hash == before_hash
        assert len(manager.machines) == 1
        assert list(machine_dir.glob("*.yaml")) == [existing_file]

    def test_bundled_profile_is_the_committed_file_verbatim(self):
        """
        The profile shipped in the package's resources (and so in the
        .app) is byte-identical to docs/profiles/ilab-614.yaml, and is
        what ILAB_614_PROFILE holds.
        """
        assert PROFILE_FILE.read_bytes() == PROFILE_YAML.read_bytes()
        with open(PROFILE_YAML) as f:
            assert ILAB_614_PROFILE == yaml.safe_load(f)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS config paths")
def test_fresh_macos_install_seeds_the_committed_profile(tmp_path):
    """
    With no ~/Library/Application Support/swiftcut yet, the app's own
    config-path and seeding code writes the committed profile there.
    Runs in a child process with HOME pointed at an empty directory;
    nothing connects, since only the UI starts auto-connect.
    """
    env = dict(os.environ)
    env.pop("RAYFORGE_CONFIG_DIR", None)
    env["HOME"] = str(tmp_path)
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from swiftcut.context import get_context; "
                "get_context().machine_mgr"
            ),
        ],
        env=env,
        cwd=REPO_ROOT,
        check=True,
        timeout=120,
    )

    machine_dir = (
        tmp_path / "Library" / "Application Support" / "swiftcut" / "machines"
    )
    seeded_files = list(machine_dir.glob("*.yaml"))
    assert len(seeded_files) == 1
    with open(seeded_files[0]) as f:
        seeded = yaml.safe_load(f)
    with open(PROFILE_YAML) as f:
        committed = yaml.safe_load(f)

    # The machine's uid is the file's name, not a field in it.
    assert seeded["machine"].pop("name") == "ilab-614"
    committed["machine"].pop("name")
    assert seeded == committed


LEGACY_ID = "3c1aed0c-0000-4000-8000-000000000001"


def test_migrated_dir_with_only_driverless_profile_seeds_ilab_614(
    tmp_path, task_mgr, monkeypatch, caplog
):
    """
    A legacy Rayforge config migrated in brings a driverless "Default
    Machine" that config.yaml selects. Launch still seeds ilab-614 and
    makes it active; the legacy file stays on disk byte-identical.
    """
    from swiftcut import config
    from swiftcut import context as context_module
    from swiftcut.context import get_context
    from swiftcut.machine.models.dialect import GRBL_DIALECT
    from swiftcut.machine.models.dialect_manager import DialectManager
    from swiftcut.shared import tasker

    config_dir = tmp_path / "config"
    dialect_dir = config_dir / "dialects"
    machine_dir = config_dir / "machines"
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "DIALECT_DIR", dialect_dir)
    monkeypatch.setattr(config, "MACHINE_DIR", machine_dir)
    monkeypatch.setattr(tasker.task_mgr, "_instance", task_mgr)

    # Like the real migrated profile, it points at its own dialect
    # copy, so loading it runs no dialect migration (which would
    # rewrite the file).
    dialect = GRBL_DIALECT.copy_as_custom(new_label="Legacy")
    DialectManager(dialect_dir).add_dialect(dialect)
    machine_dir.mkdir(parents=True)
    legacy_file = machine_dir / f"{LEGACY_ID}.yaml"
    legacy_bytes = (
        "machine:\n"
        "  name: Default Machine\n"
        "  driver: null\n"
        "  driver_args: {}\n"
        f"  dialect_uid: {dialect.uid}\n"
    ).encode()
    legacy_file.write_bytes(legacy_bytes)
    (config_dir / "config.yaml").write_text(f"machine: {LEGACY_ID}\n")

    try:
        with caplog.at_level(logging.WARNING):
            context = get_context()
            context.initialize_lite_context(machine_dir)

        assert len(list(machine_dir.glob("*.yaml"))) == 2
        assert legacy_file.read_bytes() == legacy_bytes
        assert len(context.machine_mgr.machines) == 2
        assert context.config.machine.name == "ilab-614"
        assert context.config.machine.driver_name == "RuidaDriver"
        assert any(
            r.levelno == logging.WARNING and "Default Machine" in r.message
            for r in caplog.records
        )
    finally:
        context_module._context_instance = None


def test_committed_default_cut_scale_is_a_gentle_test_cut():
    """
    The Cut Scale must never ship as a full-power or full-speed cut:
    the committed default is a gentle 20 mm/s at 30 % power.
    """
    machine = ILAB_614_PROFILE["machine"]
    speed = machine["cut_scale_speed_mm_s"]
    power = machine["cut_scale_power_pct"]

    assert speed == 20.0
    assert power == 30.0
    assert power <= 50
    assert speed <= 100


def test_active_machine_is_never_a_driverless_profile(lite_context):
    manager = lite_context.machine_mgr
    driverless = Machine(lite_context)
    driverless.name = "Driverless"
    manager.add_machine(driverless)

    assert manager.pick_auto_machine().name == "ilab-614"
    assert manager.has_driver(driverless) is False
