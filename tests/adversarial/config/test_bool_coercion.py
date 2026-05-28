"""Bool coercion attacks on PetasosConfig (PET-25 CFG-02/CFG-03)."""

from __future__ import annotations

import pytest

from petasos.config import _BOOL_FIELDS, PetasosConfig


@pytest.mark.parametrize("field", sorted(_BOOL_FIELDS))
def test_from_dict_all_toggles_falsy_int(field: str) -> None:
    with pytest.raises(TypeError, match=f"{field} must be a bool"):
        PetasosConfig.from_dict({field: 0})


@pytest.mark.parametrize("field", sorted(_BOOL_FIELDS))
def test_from_dict_all_toggles_truthy_non_bool(field: str) -> None:
    with pytest.raises(TypeError, match=f"{field} must be a bool"):
        PetasosConfig.from_dict({field: 1})
