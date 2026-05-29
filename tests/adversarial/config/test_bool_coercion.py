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


# --- CFG-02 (PET-24): pin TypeError-not-ValueError + bool round-trip ---------


def test_anonymize_truthy_int_raises_typeerror_not_valueerror() -> None:
    # PET-24: the ledger expected ValueError; the implemented coercion raises
    # TypeError (the correct exception for a type violation). Pin current behavior.
    with pytest.raises(TypeError, match="anonymize must be a bool"):
        PetasosConfig.from_dict({"anonymize": 1})


def test_normalize_nfkc_falsy_int_raises_typeerror() -> None:
    with pytest.raises(TypeError, match="normalize_nfkc must be a bool"):
        PetasosConfig.from_dict({"normalize_nfkc": 0})


def test_bool_values_roundtrip() -> None:
    cfg = PetasosConfig.from_dict({"anonymize": True, "normalize_nfkc": False})
    assert cfg.anonymize is True
    assert cfg.normalize_nfkc is False
    # round-trip through to_dict/from_dict preserves real bool toggles
    rt = PetasosConfig.from_dict(cfg.to_dict())
    assert rt.anonymize is True
    assert rt.normalize_nfkc is False
