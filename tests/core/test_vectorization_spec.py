"""
A spec's ppi: None is Auto (the file's own units per inch), the
default of a new vector or trace spec. A spec saved before Auto keeps
what it had, 96 when it has no ppi, so its file comes in as it did.
"""

import pytest

from swiftcut.core.vectorization_spec import (
    PassthroughSpec,
    ProceduralSpec,
    TraceSpec,
    VectorizationSpec,
)


@pytest.mark.parametrize("spec_type", [PassthroughSpec, TraceSpec])
class TestPpi:
    def test_a_new_spec_is_auto_and_stays_auto(self, spec_type):
        spec = spec_type()

        restored = VectorizationSpec.from_dict(spec.to_dict())

        assert spec.ppi is None
        assert restored == spec

    @pytest.mark.parametrize("ppi", [72.0, 96.0])
    def test_a_saved_ppi_is_kept(self, spec_type, ppi):
        saved = {**spec_type().to_dict(), "ppi": ppi}

        assert VectorizationSpec.from_dict(saved).ppi == ppi

    def test_a_spec_saved_without_ppi_is_96(self, spec_type):
        saved = spec_type().to_dict()
        del saved["ppi"]

        assert VectorizationSpec.from_dict(saved).ppi == 96.0


def test_a_procedural_spec_keeps_96():
    assert ProceduralSpec().ppi == 96.0
    assert ProceduralSpec.from_dict({"type": "ProceduralSpec"}).ppi == 96.0
