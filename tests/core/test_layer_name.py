import pytest

from swiftcut.core.layer_name import STEP_TYPES, parse_layer_name
from swiftcut.core.step_registry import step_registry

NAMES = [
    # Operation words alone, any case.
    ("cut", ("cut", None, None)),
    ("CUT", ("cut", None, None)),
    ("Corte", ("cut", None, None)),
    ("cortar", ("cut", None, None)),
    ("scan", ("scan", None, None)),
    ("Score", ("scan", None, None)),
    ("mark", ("scan", None, None)),
    ("ENGRAVE", ("engrave", None, None)),
    ("GRAVAR", ("engrave", None, None)),
    ("raster", ("engrave", None, None)),
    ("Fill", ("engrave", None, None)),
    # Operation, material and thickness, any order and separators.
    ("Scan 3mm MDF", ("scan", "mdf", 3.0)),
    ("scan 3mm mdf", ("scan", "mdf", 3.0)),
    ("acrylic_6mm-cut", ("cut", "acrylic", 6.0)),
    ("MDF.3.cut", ("cut", "mdf", 3.0)),
    ("cut 3 mm mdf", ("cut", "mdf", 3.0)),
    ("6mm_foamboard_cut", ("cut", "foamboard", 6.0)),
    ("foam-3mm-score", ("scan", "foamboard", 3.0)),
    ("engrave 2.5mm acrylic", ("engrave", "acrylic", 2.5)),
    ("engrave 2,5mm acrylic", ("engrave", "acrylic", 2.5)),
    ("2.5mm.mdf.cut", ("cut", "mdf", 2.5)),
    # Accents do not count.
    ("Acrílico 3mm corte", ("cut", "acrylic", 3.0)),
    ("ACRÍLICO_6MM_GRAVAR", ("engrave", "acrylic", 6.0)),
    # Material or thickness without an operation.
    ("MDF", (None, "mdf", None)),
    ("acrilico 3mm", (None, "acrylic", 3.0)),
    ("Layer 1", (None, None, 1.0)),
    ("Layer 1 cut 3mm", ("cut", None, 3.0)),
    # Two different operations, materials or thicknesses: no guess.
    ("cut engrave", (None, None, None)),
    ("score-cut 3mm mdf", (None, "mdf", 3.0)),
    ("cut mdf acrylic", ("cut", None, None)),
    ("cut 3mm 6mm", ("cut", None, None)),
    ("cut cortar corte", ("cut", None, None)),
    # Near misses: not whole words.
    ("cutting", (None, None, None)),
    ("layer", (None, None, None)),
    ("Shortcut", (None, None, None)),
    ("scanner", (None, None, None)),
    ("engraved", (None, None, None)),
    ("mdf3", (None, None, None)),
    ("3d cut", ("cut", None, None)),
    ("", (None, None, None)),
]


@pytest.mark.parametrize("name, expected", NAMES, ids=[n for n, _ in NAMES])
def test_a_layer_name_gives_operation_material_and_thickness(name, expected):
    assert parse_layer_name(name) == expected


def test_the_table_holds_at_least_thirty_names():
    assert len(NAMES) >= 30


def test_each_operation_makes_a_registered_step(context_initializer):
    for step_type in STEP_TYPES.values():
        assert step_registry.get(step_type) is not None, step_type
