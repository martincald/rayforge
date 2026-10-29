from unittest.mock import MagicMock

import pytest
from laser_essentials.steps import ContourStep, ScanStep
from laser_essentials.worker import register_steps

from swiftcut.core.step import Step
from swiftcut.core.step_registry import StepRegistry, step_registry
from swiftcut.core.workpiece import WorkPiece


def _context(max_cut_speed):
    context = MagicMock()
    machine = MagicMock()
    machine.max_cut_speed = max_cut_speed
    machine.max_travel_speed = 60000
    machine.acceleration = 3000
    default_head = MagicMock()
    default_head.uid = "test-laser-uid"
    default_head.kerf_mm = 0.1
    machine.get_default_laser_head.return_value = default_head
    machine.get_pwm_params.return_value = None
    context.machine = machine
    return context


def test_scan_is_its_own_registered_type():
    assert step_registry.get("ScanStep") is ScanStep
    step = ScanStep()
    assert step.typelabel == "Scan"
    assert step.name == "Scan"
    assert ScanStep.ASSEMBLER_NAME == ContourStep.ASSEMBLER_NAME


def test_create_defaults_to_low_power_and_500_mm_s():
    step = ScanStep.create(_context(max_cut_speed=60000))

    assert step.power == pytest.approx(0.10)
    assert step.min_power == pytest.approx(0.10)
    assert step.cut_speed == 30000  # mm/min: 500 mm/s


def test_create_speed_stays_under_the_machine_ceiling():
    step = ScanStep.create(_context(max_cut_speed=5000))

    assert step.cut_speed == 5000


def test_create_is_a_cuts_otherwise():
    context = _context(max_cut_speed=60000)
    scan = ScanStep.create(context)
    cut = ContourStep.create(context)
    cut.power = scan.power
    cut.cut_speed = scan.cut_speed

    assert scan.selected_head_uid == cut.selected_head_uid
    assert scan.offset_mm == cut.offset_mm
    assert scan.get_settings() == cut.get_settings()
    names = [t["name"] for t in scan.per_workpiece_transformers_dicts]
    assert names == [t["name"] for t in cut.per_workpiece_transformers_dicts]
    names = [t["name"] for t in scan.per_step_transformers_dicts]
    assert names == [t["name"] for t in cut.per_step_transformers_dicts]
    # The lead-in auto distance follows the scan's own speed.
    lead_in = next(
        t
        for t in scan.per_workpiece_transformers_dicts
        if t["name"] == "LeadInOutTransformer"
    )
    cut_lead_in = next(
        t
        for t in ContourStep.create(context).per_workpiece_transformers_dicts
        if t["name"] == "LeadInOutTransformer"
    )
    assert lead_in["lead_in_mm"] > cut_lead_in["lead_in_mm"]


def test_scan_round_trips_as_scan():
    step = ScanStep(name="Mark")
    data = step.to_dict()
    assert data["step_type"] == "ScanStep"

    restored = Step.from_dict(data)

    assert type(restored) is ScanStep
    assert restored.name == "Mark"
    assert restored.typelabel == "Scan"


def test_same_numbers_give_the_same_compute_input(machine):
    """A Scan and a Cut with the same numbers hand the pipeline the
    same assembler spec, settings and initial ops."""
    scan = ScanStep(name="s")
    cut = ContourStep(name="c")
    for step in (scan, cut):
        step.power = 0.2
        step.cut_speed = 12000
        step.travel_speed = 30000
        step.cut_side = "OUTSIDE"
        step.offset_mm = 0.1
        step.overcut = 0.3
    wp = WorkPiece(name="wp")

    _, scan_payload = scan.build_compute_payload(machine, wp)
    _, cut_payload = cut.build_compute_payload(machine, wp)

    assert scan_payload.assembler.spec == cut_payload.assembler.spec
    assert scan.get_assembler_kwargs(machine, wp) == (
        cut.get_assembler_kwargs(machine, wp)
    )
    assert scan.assembler_token_params(machine, wp) == (
        cut.assembler_token_params(machine, wp)
    )
    assert scan.get_settings() == cut.get_settings()
    assert scan.create_initial_ops().to_dict() == (
        cut.create_initial_ops().to_dict()
    )


def test_add_step_menu_order():
    """The add-step menu lists Cut, Engrave, Scan, Frame."""
    registry = StepRegistry()
    register_steps(registry)

    labels = [f.__self__.TYPELABEL for f in registry.get_factories()]

    assert labels == ["Cut", "Engrave", "Scan", "Frame"]
