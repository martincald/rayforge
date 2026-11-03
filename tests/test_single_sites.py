"""
The single-site invariants of CLAUDE.md section 9, as source scans.

Units: the model stores mm/min, the UI shows mm/s, the encoder emits
um/s, with one conversion per value path. Every multiply or divide by
60 in swiftcut/ is listed below with the path it serves, so a new one
fails here until someone says which path it belongs to.

Axis direction: a visual jog direction becomes signed native deltas
in one place, MachinePanel.calculate_jog. The jog panel's _jog_deltas,
the start-corner pre-move, Home's park and Go/Cut Scale all ask it.
"""

import ast
from pathlib import Path

SWIFTCUT = Path(__file__).resolve().parents[1] / "swiftcut"
POST = "builtin_addons/rayforge-addon-post/post_processors/transformers"

# (file under swiftcut/, enclosing function): the value path it serves.
SIXTY_SITES = {
    ("core/recipe_manager.py", "bundle_recipe_dicts"): "recipe mm/s in",
    ("image/lightburn/importer.py", "_build_step_config"): "LightBurn mm/s in",
    ("ui_gtk/machine/jog_widget.py", "confirm"): (
        "Cut Scale dialog mm/min -> profile mm/s"
    ),
    ("ui_gtk/machine/jog_widget.py", "_on_cut_scale_clicked"): (
        "profile mm/s -> Cut Scale dialog mm/min"
    ),
    ("ui_gtk/machine/cut_scale_dialog.py", None): "default, 20 mm/s",
    ("ui_gtk/canvas/worldsurface.py", "on_scroll_decelerate"): (
        "pan velocity per frame, not a speed unit"
    ),
    ("shared/util/time_format.py", "format_hours_to_hm"): "time",
    ("shared/util/time_format.py", "format_seconds"): "time",
    (f"{POST}/lead_in_out_transformer.py", "calculate_auto_distance"): (
        "kinematics only"
    ),
    (f"{POST}/overscan_transformer.py", "calculate_auto_distance"): (
        "kinematics only"
    ),
    ("machine/driver/driver.py", "acceleration_run_up_mm"): (
        "kinematics only"
    ),
    ("machine/driver/ruida/ruida_driver.py", "_set_travel_speed"): (
        "interactive speed to the wire, the only one"
    ),
    ("machine/driver/ruida/ruida_driver.py", "_hold_jog"): (
        "hold step length, internal"
    ),
    ("machine/driver/ruida/ruida_driver.py", "_wait_for_jog_settled"): (
        "settle timeout, internal"
    ),
}


def _sixty_sites() -> set[tuple[str, str | None]]:
    """Every * 60 and / 60 in swiftcut/, by file and function."""
    found = set()
    for path in SWIFTCUT.rglob("*.py"):
        if "tests" in path.relative_to(SWIFTCUT).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(SWIFTCUT).as_posix()
        for func, node in _walk_with_function(tree, None):
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, (ast.Mult, ast.Div, ast.FloorDiv))
                and any(
                    isinstance(side, ast.Constant) and side.value == 60
                    for side in (node.left, node.right)
                )
            ):
                found.add((rel, func))
    return found


def _walk_with_function(node, func):
    for child in ast.iter_child_nodes(node):
        name = func
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = child.name
        yield name, child
        yield from _walk_with_function(child, name)


def test_every_minute_conversion_is_a_known_site():
    assert _sixty_sites() == set(SIXTY_SITES)


def test_the_encoder_converts_job_speeds_in_one_method():
    encoder = SWIFTCUT / "machine/driver/ruida/ruida_encoder.py"
    source = encoder.read_text(encoding="utf-8")
    assert source.count("SECONDS_PER_MINUTE)") == 1
    assert "def _speed_to_um_s" in source


def test_only_calculate_jog_maps_a_direction_to_signed_deltas():
    """A dict keyed by JogDirection members is a direction mapping."""
    sites = set()
    for path in SWIFTCUT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(SWIFTCUT).as_posix()
        for func, node in _walk_with_function(tree, None):
            if isinstance(node, ast.Dict) and any(
                isinstance(key, ast.Attribute)
                and isinstance(key.value, ast.Name)
                and key.value.id == "JogDirection"
                for key in node.keys
            ):
                sites.add((rel, func))
    assert sites == {("machine/models/machine_panel.py", "calculate_jog")}
