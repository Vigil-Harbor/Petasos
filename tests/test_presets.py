"""Tests for petasos.console._presets — the PET-124 strength-preset registry.

Pure, ML-free, 3.10-clean: the registry, contract, validation, floor, and
custom-detection guards. Mirrors tests/test_config_meta.py's section-registry
tests (PET-114).
"""

import dataclasses

import pytest

from petasos.config import PetasosConfig
from petasos.console._config_meta import _FIELD_META
from petasos.console._presets import (
    _PRESET_OWNED_FIELDS,
    _PRESET_REGISTRY,
    StrengthPreset,
    generate_preset_metadata,
    resolve_active_preset,
)
from petasos.scanners.minimal import _UNSUPPRESSIBLE_RULE_IDS, MinimalScanner

# The exact owned-field set (D8): 13 config-level strength fields, no reliability
# or profile levers. Pinned here so a drift in either the registry or the
# allowlist is caught.
_EXPECTED_OWNED_FIELDS = frozenset(
    {
        "fail_mode",
        "tier1_threshold",
        "tier2_threshold",
        "tier3_threshold",
        "presidio_score_threshold",
        "anonymize",
        "tool_guard_enabled",
        "normalize_nfkc",
        "strip_zero_width",
        "map_homoglyphs",
        "detect_rtl_override",
        "fold_leet",
        "decode_encoded_payloads",
    }
)


def _config_from_preset(preset: StrengthPreset) -> PetasosConfig:
    """Build a PetasosConfig by applying a preset over the shipped defaults."""
    return PetasosConfig.from_dict({**PetasosConfig().to_dict(), **dict(preset.overrides)})


def test_preset_registry_frozen_and_ordered() -> None:
    # Tuple typed Final; frozen dataclass rejects attribute assignment.
    assert isinstance(_PRESET_REGISTRY, tuple)
    assert len(_PRESET_REGISTRY) == 5
    preset = _PRESET_REGISTRY[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        preset.label = "mutated"  # type: ignore[misc]

    # order is contiguous 0..4, unique and ascending in registry order.
    orders = [p.order for p in _PRESET_REGISTRY]
    assert orders == [0, 1, 2, 3, 4]
    assert len(set(orders)) == len(orders)

    keys = [p.key for p in _PRESET_REGISTRY]
    assert keys == ["tin", "bronze", "iron", "steel", "titanium"]

    # generate_preset_metadata returns fresh objects each call: mutating the
    # result cannot corrupt the registry, and overrides is a plain dict.
    a = generate_preset_metadata()
    b = generate_preset_metadata()
    assert a == b
    assert a is not b
    assert a[0] is not b[0]
    assert isinstance(a[0]["overrides"], dict)
    a[0]["label"] = "MUTATED"
    a[0]["overrides"]["fail_mode"] = "tampered"
    fresh = generate_preset_metadata()
    assert fresh[0]["label"] != "MUTATED"
    assert fresh[0]["overrides"]["fail_mode"] != "tampered"

    # ordered, with the expected entry shape.
    assert [p["order"] for p in fresh] == list(range(len(fresh)))
    for entry in fresh:
        assert set(entry.keys()) == {"key", "label", "order", "description", "overrides"}
        assert isinstance(entry["key"], str) and entry["key"]
        assert isinstance(entry["label"], str) and entry["label"].strip()
        assert isinstance(entry["description"], str) and entry["description"].strip()
        assert isinstance(entry["order"], int)


def test_strength_preset_is_frozen_slots_dataclass() -> None:
    assert dataclasses.is_dataclass(StrengthPreset)
    params = StrengthPreset.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True
    # slots=True means no per-instance __dict__.
    sample = _PRESET_REGISTRY[0]
    assert not hasattr(sample, "__dict__")
    # overrides is an immutable mapping (cannot be mutated in place).
    with pytest.raises(TypeError):
        sample.overrides["fail_mode"] = "tampered"  # type: ignore[index]


def test_every_preset_field_has_field_meta_entry() -> None:
    # Mirrors PET-114's orphan-section contract: every overrides key is a known
    # config field with a _FIELD_META entry (no orphan/typo fields).
    for preset in _PRESET_REGISTRY:
        for key in preset.overrides:
            assert key in _FIELD_META, f"{preset.key}: unknown overrides field {key!r}"


def test_all_presets_cover_same_fields() -> None:
    # Symmetric comparator: each preset's key set equals _PRESET_OWNED_FIELDS,
    # which equals the pinned expected set.
    assert _PRESET_OWNED_FIELDS == _EXPECTED_OWNED_FIELDS
    assert len(_PRESET_OWNED_FIELDS) == 13
    for preset in _PRESET_REGISTRY:
        assert set(preset.overrides.keys()) == _PRESET_OWNED_FIELDS, preset.key


def test_preset_bundles_distinct() -> None:
    # Resolution is unambiguous: all five overrides mappings are pairwise distinct.
    seen: list[dict[str, bool | float | str]] = []
    for preset in _PRESET_REGISTRY:
        d = dict(preset.overrides)
        assert d not in seen, f"{preset.key} duplicates an earlier bundle"
        seen.append(d)


def test_preset_bundle_validates() -> None:
    # Each preset's full bundle constructs (ascending tiers, finite values, valid
    # fail_mode).
    for preset in _PRESET_REGISTRY:
        cfg = _config_from_preset(preset)
        assert cfg.fail_mode in ("open", "degraded", "closed")
        assert cfg.tier1_threshold < cfg.tier2_threshold < cfg.tier3_threshold

    # Guard-is-real: a hand-edited bundle that breaks the ascending invariant is
    # rejected by from_dict (so a future numeric mistake fails loudly).
    with pytest.raises(ValueError):
        PetasosConfig.from_dict({**PetasosConfig().to_dict(), "tier1_threshold": 31.0})


def test_preset_bundle_round_trips() -> None:
    # Apply then to_dict/from_dict is stable (config.yaml round-trip contract).
    for preset in _PRESET_REGISTRY:
        cfg = _config_from_preset(preset)
        round_tripped = PetasosConfig.from_dict(cfg.to_dict())
        assert round_tripped.to_dict() == cfg.to_dict(), preset.key


def test_no_preset_lowers_tier3_floor() -> None:
    # Every preset's constructed tier3_threshold sits at or above the 30.0 floor.
    for preset in _PRESET_REGISTRY:
        cfg = _config_from_preset(preset)
        assert cfg.tier3_threshold >= 30.0, preset.key

    # Sanity: the floor is real — a sub-floor tier3 is rejected at construction.
    with pytest.raises(ValueError):
        PetasosConfig.from_dict(
            {**PetasosConfig().to_dict(), "tier2_threshold": 20.0, "tier3_threshold": 29.0}
        )


def test_no_preset_touches_unsuppressible_rules() -> None:
    # Presets are config-only: no owned field is a suppression lever, so a preset
    # is structurally incapable of reaching the unsuppressible-rule floor.
    assert _UNSUPPRESSIBLE_RULE_IDS, "sanity: the unsuppressible set is non-empty"
    assert "suppress_rules" not in _PRESET_OWNED_FIELDS
    assert "confidence_floor" not in _PRESET_OWNED_FIELDS

    # End-to-end: after applying each preset, building MinimalScanner the way
    # pipeline.py does (decode toggle from config, no profile suppression) leaves
    # every unsuppressible id active.
    for preset in _PRESET_REGISTRY:
        cfg = _config_from_preset(preset)
        scanner = MinimalScanner(decode_encoded_payloads=cfg.decode_encoded_payloads)
        assert scanner._suppress_rules == frozenset(), preset.key
        assert _UNSUPPRESSIBLE_RULE_IDS.isdisjoint(scanner._suppress_rules), preset.key


def test_custom_detection() -> None:
    # A default config resolves to Iron (the shipped default, D6).
    assert resolve_active_preset(PetasosConfig()) == "iron"

    # Editing one owned field flips to Custom (None).
    assert resolve_active_preset(PetasosConfig(fail_mode="open")) is None

    # An exact preset projection resolves back to that preset's key.
    steel = next(p for p in _PRESET_REGISTRY if p.key == "steel")
    assert resolve_active_preset(_config_from_preset(steel)) == "steel"

    # Changing a NON-owned field does not flip the dial (still Iron).
    assert resolve_active_preset(PetasosConfig(alert_per_minute_cap=7)) == "iron"

    # Redaction never perturbs resolution: no owned field is a secret.
    assert resolve_active_preset(PetasosConfig().to_dict(redact_secrets=True)) == "iron"
    assert (
        resolve_active_preset(PetasosConfig(hash_key="s3cret").to_dict(redact_secrets=True))
        == "iron"
    )


def test_resolve_active_preset_accepts_dict_and_object() -> None:
    # The comparator takes either a PetasosConfig or an already-built dict.
    cfg = PetasosConfig()
    assert resolve_active_preset(cfg) == resolve_active_preset(cfg.to_dict()) == "iron"
    # A dict missing owned keys resolves to None rather than raising.
    assert resolve_active_preset({"fail_mode": "degraded"}) is None
    assert resolve_active_preset({}) is None


def test_iron_equals_shipped_defaults() -> None:
    # Pins the zero-behavior-change invariant (D6): PetasosConfig() projected to
    # the owned fields equals Iron's overrides exactly.
    iron = next(p for p in _PRESET_REGISTRY if p.key == "iron")
    defaults = PetasosConfig().to_dict()
    projection = {k: defaults[k] for k in _PRESET_OWNED_FIELDS}
    assert projection == dict(iron.overrides)
