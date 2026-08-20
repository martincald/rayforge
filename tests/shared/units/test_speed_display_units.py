"""
Tests for the mm/s speed presentation layer.

Speeds are stored in mm/min throughout the model. The UI displays and
accepts mm/s and converts at the widget boundary, so nothing about
persisted documents or machine profiles may change.
"""

import subprocess
from pathlib import Path

import pytest

from rayforge.core.config import Config
from rayforge.core.step import Step
from rayforge.machine.models.machine import Machine
from rayforge.shared.units.definitions import (
    get_base_unit_for_quantity,
    get_unit,
    get_units_for_quantity,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
UI_GTK_DIR = REPO_ROOT / "rayforge" / "ui_gtk"


class TestSpeedUnitRegistry:
    """mm/min stays the storage base but is never offered to the user."""

    def test_base_unit_is_still_mm_per_minute(self):
        base = get_base_unit_for_quantity("speed")
        assert base is not None
        assert base.name == "mm/min"

    def test_mm_per_minute_is_not_selectable(self):
        unit = get_unit("mm/min")
        assert unit is not None
        assert unit.selectable is False
        assert unit not in get_units_for_quantity("speed")

    def test_mm_per_second_is_offered(self):
        assert get_unit("mm/s") in get_units_for_quantity("speed")

    def test_display_conversion_is_a_factor_of_sixty(self):
        mm_s = get_unit("mm/s")
        assert mm_s is not None
        assert mm_s.from_base(600.0) == pytest.approx(10.0)
        assert mm_s.to_base(10.0) == pytest.approx(600.0)


class TestConfigSpeedPreference:
    """The speed preference defaults to, and is coerced to, mm/s."""

    def test_default_preference_is_mm_per_second(self):
        assert Config().unit_preferences["speed"] == "mm/s"

    def test_persisted_mm_per_minute_is_coerced(self):
        """A config written before this change must not resurrect
        mm/min in the UI."""
        data = {
            "unit_preferences": {
                "length": "mm",
                "speed": "mm/min",
                "acceleration": "mm/s²",
            }
        }
        config = Config.from_dict(data, get_machine_by_id=lambda _uid: None)

        assert config.unit_preferences["speed"] == "mm/s"

    def test_persisted_selectable_preference_is_kept(self):
        data = {
            "unit_preferences": {
                "length": "in",
                "speed": "in/min",
                "acceleration": "mm/s²",
            }
        }
        config = Config.from_dict(data, get_machine_by_id=lambda _uid: None)

        assert config.unit_preferences["length"] == "in"
        assert config.unit_preferences["speed"] == "in/min"


class TestStoredSpeedsUnchanged:
    """Model and persistence keep mm/min values byte for byte."""

    def test_machine_profile_round_trips_identically(self, lite_context):
        """A profile saved before this change loads with the same
        internal speed values."""
        saved = {
            "machine": {
                "name": "Pre-change profile",
                "speeds": {
                    "max_cut_speed": 1234,
                    "max_travel_speed": 5678,
                    "acceleration": 900,
                },
            }
        }
        machine = Machine.from_dict(saved, context=lite_context)

        assert machine.max_cut_speed == 1234
        assert machine.max_travel_speed == 5678
        assert machine.acceleration == 900

        speeds = machine.to_dict()["machine"]["speeds"]
        assert speeds == saved["machine"]["speeds"]

    def test_machine_defaults_are_unchanged(self, lite_context):
        machine = Machine(lite_context)

        assert machine.max_travel_speed == 3000
        assert machine.max_cut_speed == 1000

    def test_step_speeds_round_trip_identically(self):
        step = Step("test")
        step.cut_speed = 777
        step.travel_speed = 4321

        restored = Step.from_dict(step.to_dict())

        assert restored.cut_speed == 777
        assert restored.travel_speed == 4321


def test_no_mm_per_minute_string_in_ui_gtk():
    """The GTK layer must not name mm/min anywhere."""
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", "mm/min", str(UI_GTK_DIR)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.stdout == "", f"mm/min found in ui_gtk:\n{result.stdout}"
