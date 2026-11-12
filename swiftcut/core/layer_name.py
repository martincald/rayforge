"""
What an imported layer's name asks for: an operation, a material and
a thickness, read from words like "Scan 3mm MDF" or "acrylic_6mm-cut".
"""

import re
import unicodedata

CUT = "cut"
SCAN = "scan"
ENGRAVE = "engrave"

# The step type each operation makes, by class name.
STEP_TYPES = {
    CUT: "ContourStep",
    SCAN: "ScanStep",
    ENGRAVE: "EngraveStep",
}

_OPERATION_WORDS = {
    "cut": CUT,
    "corte": CUT,
    "cortar": CUT,
    "scan": SCAN,
    "score": SCAN,
    "mark": SCAN,
    "engrave": ENGRAVE,
    "gravar": ENGRAVE,
    "raster": ENGRAVE,
    "fill": ENGRAVE,
}

# Material words, each to the uid of the bundled recipes' material.
_MATERIAL_WORDS = {
    "mdf": "mdf",
    "acrylic": "acrylic",
    "acrilico": "acrylic",
    "foamboard": "foamboard",
    "foam": "foamboard",
}

# A number standing on its own, with a decimal point or comma, and
# "mm" after it or not.
_THICKNESS = re.compile(r"(?<![a-z0-9])(\d+(?:[.,]\d+)?)\s*(mm)?(?![a-z0-9])")
_SEPARATORS = re.compile(r"[^a-z0-9]+")

LayerNameIntent = tuple[str | None, str | None, float | None]


def parse_layer_name(name: str) -> LayerNameIntent:
    """
    The (operation, material uid, thickness in mm) a layer's name
    gives, each None where it gives none. Case and accents do not
    count; words are whole words between any separators, in any order.
    Two different operations, materials or thicknesses give none of
    that kind. A number with "mm" wins over a bare number.
    """
    text = _plain(name)
    numbers = []
    for match in _THICKNESS.finditer(text):
        value = float(match.group(1).replace(",", "."))
        numbers.append((value, match.group(2) is not None))
    words = _SEPARATORS.split(_THICKNESS.sub(" ", text))
    with_unit = [value for value, unit in numbers if unit]
    thicknesses = with_unit or [value for value, _unit in numbers]
    return (
        _only(_OPERATION_WORDS.get(word) for word in words),
        _only(_MATERIAL_WORDS.get(word) for word in words),
        _only(thicknesses),
    )


def _plain(name: str) -> str:
    """The name in lower case, accents taken off its letters."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold()


def _only(values):
    """The one value given (None aside), or None for none or several."""
    found = {value for value in values if value is not None}
    return found.pop() if len(found) == 1 else None
