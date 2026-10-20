"""The fields the Grbl dialects share, from one place."""

from swiftcut.machine.models.dialect.grbl import GRBL_DIALECT, grbl_common
from swiftcut.machine.models.dialect.grbl_dynamic import GRBL_DYNAMIC_DIALECT
from swiftcut.machine.models.dialect.grbl_raster import GRBL_RASTER_DIALECT


def test_every_grbl_dialect_carries_the_common_fields():
    common = grbl_common()
    for dialect in (GRBL_DIALECT, GRBL_DYNAMIC_DIALECT, GRBL_RASTER_DIALECT):
        for field, value in common.items():
            assert getattr(dialect, field) == value, (dialect.uid, field)


def test_no_two_dialects_share_a_list():
    assert GRBL_DIALECT.preamble is not GRBL_RASTER_DIALECT.preamble
    assert GRBL_DYNAMIC_DIALECT.postscript is not GRBL_DIALECT.postscript
    assert grbl_common()["preamble"] is not grbl_common()["preamble"]
