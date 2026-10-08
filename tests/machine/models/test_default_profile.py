"""
Tests for the bundled machine profiles (Packages B and H).

A fresh install seeds two machine profiles, "ilab-614", built from the
shop's real Duplotech-1490 Ruida machine, and "ilab-626", the same
machine with a 900x900mm bed, instead of a bare 200x200mm placeholder.
See docs/profiles/ilab-614.yaml and docs/profiles/ilab-626.yaml for
the canonical profiles they embed verbatim.
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
    BUNDLED_NAMES,
    ILAB_614_PROFILE,
    ILAB_626_PROFILE,
    ILAB_626_PROFILE_FILE,
    PROFILE_FILE,
)
from swiftcut.machine.models.machine import Machine, Origin, StartCorner
from swiftcut.machine.models.manager import MachineManager

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE_YAML = REPO_ROOT / "docs" / "profiles" / "ilab-614.yaml"
ILAB_626_YAML = REPO_ROOT / "docs" / "profiles" / "ilab-626.yaml"
ILAB_626_ID = "b892c06c-502e-45e0-8b02-4c91dee261bb"


def _by_name(manager) -> dict[str, Machine]:
    return {m.name: m for m in manager.machines.values()}


@pytest.fixture
def seeded_machine_mgr(lite_context, tmp_path):
    """
    A MachineManager on an empty machines directory, seeded the way a
    fresh install is. lite_context pre-seeds an inert machine instead,
    so tests never get the auto-connecting ilab-614 by accident.
    """
    manager = MachineManager(tmp_path / "fresh_machines")
    manager.ensure_default_machine()
    return manager


@pytest.mark.usefixtures("lite_context")
class TestIlab614DefaultProfile:
    """An empty config dir is silently seeded with both profiles."""

    def test_empty_config_dir_seeds_ilab_614(self, seeded_machine_mgr):
        machines = _by_name(seeded_machine_mgr)
        assert len(seeded_machine_mgr.machines) == 2
        assert set(machines) == {"ilab-614", "ilab-626"}
        machine = machines["ilab-614"]

        assert machine.name == "ilab-614"
        assert machine.driver_name == "RuidaDriver"
        assert machine.driver_args == {
            "connection": "usb",
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

    def test_empty_config_dir_seeds_ilab_626_with_its_own_bed_and_id(
        self, seeded_machine_mgr
    ):
        """
        ilab-626 is ilab-614 with a 900x900mm bed (read through the
        axes, which win over the legacy axis_extents key), its own
        fixed id, the same laser head and no machine hours of its own.
        """
        machines = _by_name(seeded_machine_mgr)
        ilab_614, ilab_626 = machines["ilab-614"], machines["ilab-626"]

        assert ilab_626.axis_extents == (900.0, 900.0)
        assert ilab_626.id == ILAB_626_ID
        assert ilab_626.id != ilab_614.id
        assert ilab_626.heads[0].uid == ilab_614.heads[0].uid
        assert ilab_626.machine_hours.total_hours == 0.0
        assert ilab_626.machine_hours.counters == {}
        assert ilab_626.driver_args == ilab_614.driver_args
        assert ilab_626.start_corner == ilab_614.start_corner
        assert ilab_614.axis_extents == (1400.0, 900.0)

    def test_ilab_614_driver_name_resolves_to_ruida_driver(
        self, seeded_machine_mgr
    ):
        """
        The profiles' declared driver must actually resolve to
        RuidaDriver via the driver registry, not silently fall back
        to the no-device driver.
        """
        for machine in seeded_machine_mgr.machines.values():
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
            "connection": "usb",
            "host": "192.168.1.100",
            "port": 50200,
            "jog_port": 50207,
        }
        assert "response_port" not in driver_args
        assert RuidaDriver.RESPONSE_PORT == 40200

    def test_fresh_machines_dir_seeds_a_usb_connection(self, tmp_path):
        """
        Seeding an empty machines directory gives both machines a USB
        connection, in memory and in the files written, and keeps the
        host and ports so Ethernet can still be chosen.
        """
        machine_dir = tmp_path / "fresh_machines"
        manager = MachineManager(machine_dir)

        seeded_machines = manager.ensure_default_machine()

        assert [m.name for m in seeded_machines] == list(BUNDLED_NAMES)
        for machine in seeded_machines:
            assert machine.driver_args["connection"] == "usb"
            assert machine.driver_args["host"] == "192.168.1.100"
        seeded_files = list(machine_dir.glob("*.yaml"))
        assert len(seeded_files) == 2
        for seeded_file in seeded_files:
            with open(seeded_file) as f:
                seeded = yaml.safe_load(f)
            assert seeded["machine"]["driver_args"]["connection"] == "usb"

    def test_install_with_only_ilab_614_gets_ilab_626_added(self, tmp_path):
        """
        An existing install that only has ilab-614 gets ilab-626 added
        at launch; the ilab-614 file is left byte-identical. A second
        launch then finds both and adds or rewrites nothing.
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
        [added] = manager.ensure_default_machine()

        after_hash = hashlib.sha256(existing_file.read_bytes()).hexdigest()
        assert after_hash == before_hash
        assert added.name == "ilab-626"
        assert added.axis_extents == (900.0, 900.0)
        assert sorted(machine_dir.glob("*.yaml")) == sorted(
            [existing_file, machine_dir / f"{ILAB_626_ID}.yaml"]
        )

        files = sorted(machine_dir.glob("*.yaml"))
        before = {f: f.read_bytes() for f in files}
        relaunched = MachineManager(machine_dir)
        assert relaunched.ensure_default_machine() == []
        assert sorted(machine_dir.glob("*.yaml")) == files
        assert {f: f.read_bytes() for f in files} == before

    def test_dir_with_only_the_inert_placeholder_seeds_nothing(
        self, lite_context, tmp_path
    ):
        """
        A machine with a resolvable driver that is not a bundled one,
        like the tests' inert NoDeviceDriver placeholder, keeps the
        seed off: no test may ever get an auto-connecting Ruida.
        """
        from tests.conftest import _seed_inert_machine

        machine_dir = tmp_path / "inert_machines"
        _seed_inert_machine(machine_dir, lite_context)
        files = list(machine_dir.glob("*.yaml"))

        manager = MachineManager(machine_dir)

        assert manager.ensure_default_machine() == []
        assert list(machine_dir.glob("*.yaml")) == files
        assert [m.driver_name for m in manager.machines.values()] == [
            "NoDeviceDriver"
        ]

    def test_bundled_profile_is_the_committed_file_verbatim(self):
        """
        The profiles shipped in the package's resources (and so in the
        .app) are byte-identical to docs/profiles/ilab-614.yaml and
        docs/profiles/ilab-626.yaml, and are what ILAB_614_PROFILE and
        ILAB_626_PROFILE hold.
        """
        assert PROFILE_FILE.read_bytes() == PROFILE_YAML.read_bytes()
        with open(PROFILE_YAML) as f:
            assert ILAB_614_PROFILE == yaml.safe_load(f)
        assert ILAB_626_PROFILE_FILE.read_bytes() == (
            ILAB_626_YAML.read_bytes()
        )
        with open(ILAB_626_YAML) as f:
            assert ILAB_626_PROFILE == yaml.safe_load(f)


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
    assert len(seeded_files) == 2
    seeded_by_name = {}
    for seeded_file in seeded_files:
        with open(seeded_file) as f:
            seeded = yaml.safe_load(f)
        seeded_by_name[seeded["machine"].pop("name")] = seeded
    assert set(seeded_by_name) == {"ilab-614", "ilab-626"}

    for name, committed_yaml in (
        ("ilab-614", PROFILE_YAML),
        ("ilab-626", ILAB_626_YAML),
    ):
        with open(committed_yaml) as f:
            committed = yaml.safe_load(f)
        # The machine's uid is the file's name, not a field in it.
        committed["machine"].pop("name")
        committed["machine"].pop("id", None)
        assert seeded_by_name[name] == committed
    assert (machine_dir / f"{ILAB_626_ID}.yaml").exists()


LEGACY_ID = "3c1aed0c-0000-4000-8000-000000000001"


def test_migrated_dir_with_only_driverless_profile_seeds_ilab_614(
    tmp_path, task_mgr, monkeypatch, caplog
):
    """
    A legacy Rayforge config migrated in brings a driverless "Default
    Machine" that config.yaml selects. Launch still seeds both bundled
    profiles and makes ilab-614 active; the legacy file stays on disk
    byte-identical.
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

        assert len(list(machine_dir.glob("*.yaml"))) == 3
        assert legacy_file.read_bytes() == legacy_bytes
        assert len(context.machine_mgr.machines) == 3
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


def test_active_machine_is_never_a_driverless_profile(
    lite_context, seeded_machine_mgr
):
    manager = seeded_machine_mgr
    driverless = Machine(lite_context)
    driverless.name = "Driverless"
    manager.add_machine(driverless)

    assert manager.pick_auto_machine().name == "ilab-614"
    assert manager.has_driver(driverless) is False


def test_ilab_614_is_picked_first_whatever_the_ids(lite_context, tmp_path):
    """
    The auto-picked machine is the first bundled one, ilab-614, even
    when ilab-626's fixed id sorts below ilab-614's per-install id.
    """
    machine_dir = tmp_path / "machines"
    machine_dir.mkdir()
    ilab_614_id = "ffffffff-ffff-4fff-bfff-ffffffffffff"
    (machine_dir / f"{ilab_614_id}.yaml").write_bytes(
        PROFILE_YAML.read_bytes()
    )
    manager = MachineManager(machine_dir)
    manager.ensure_default_machine()
    assert ILAB_626_ID < ilab_614_id

    picked = manager.pick_auto_machine()

    assert picked.name == "ilab-614"
    assert picked.id == ilab_614_id
