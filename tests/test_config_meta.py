"""Tests for petasos.console._config_meta."""

import dataclasses

import pytest

from petasos.config import _SECRET_FIELDS, PetasosConfig
from petasos.console._config_meta import (
    _FIELD_META,
    _SECTION_REGISTRY,
    ConfigSection,
    generate_config_metadata,
    generate_section_metadata,
)

# PET-114: canonical section render order — common controls first/open, advanced
# groups after, collapsed. Pinned here so the order + open-first coupling can't
# drift silently.
_EXPECTED_SECTION_ORDER = [
    "profiles",
    "anonymization",
    "fail_mode",
    "tool_guard",
    "scanning",
    "normalization",
    "escalation",
    "frequency",
    "audit",
    "alerting",
    "session",
]
_ADVANCED_SECTIONS = {"normalization", "escalation", "frequency", "audit", "alerting", "session"}
_COMMON_SECTIONS = {"profiles", "anonymization", "fail_mode", "tool_guard", "scanning"}


def test_every_field_present() -> None:
    """Every non-excluded PetasosConfig field appears in metadata."""
    meta = generate_config_metadata()
    meta_names = {m["name"] for m in meta}
    for f in dataclasses.fields(PetasosConfig):
        if f.name == "session_secret":
            assert f.name not in meta_names, "session_secret should be excluded"
        else:
            assert f.name in meta_names, f"Field {f.name!r} missing from metadata"


def test_session_secret_excluded() -> None:
    meta = generate_config_metadata()
    names = {m["name"] for m in meta}
    assert "session_secret" not in names


def test_bool_type_derivation() -> None:
    meta = generate_config_metadata()
    by_name = {m["name"]: m for m in meta}
    assert by_name["normalize_nfkc"]["type"] == "boolean"
    assert by_name["anonymize"]["type"] == "boolean"
    assert not by_name["normalize_nfkc"]["nullable"]


def test_number_type_derivation() -> None:
    meta = generate_config_metadata()
    by_name = {m["name"]: m for m in meta}
    assert by_name["scanner_timeout_seconds"]["type"] == "number"
    assert by_name["tier1_threshold"]["type"] == "number"


def test_enum_type_derivation() -> None:
    meta = generate_config_metadata()
    by_name = {m["name"]: m for m in meta}
    assert by_name["fail_mode"]["type"] == "enum"
    assert "values" in by_name["fail_mode"]["constraints"]
    assert "open" in by_name["fail_mode"]["constraints"]["values"]


def test_array_type_derivation() -> None:
    meta = generate_config_metadata()
    by_name = {m["name"]: m for m in meta}
    assert by_name["pii_entities"]["type"] == "array"


def test_nullable_string() -> None:
    meta = generate_config_metadata()
    by_name = {m["name"]: m for m in meta}
    assert by_name["hash_key"]["type"] == "string"
    assert by_name["hash_key"]["nullable"]
    assert by_name["profile_name"]["type"] == "string"
    assert by_name["profile_name"]["nullable"]


def test_mapping_type() -> None:
    meta = generate_config_metadata()
    by_name = {m["name"]: m for m in meta}
    assert by_name["frequency_weights"]["type"] == "object"
    assert by_name["frequency_weights"]["nullable"]


def test_secret_fields_marked_redacted() -> None:
    meta = generate_config_metadata()
    by_name = {m["name"]: m for m in meta}
    for field_name in _SECRET_FIELDS:
        assert by_name[field_name].get("redacted") is True


def test_sections_assigned() -> None:
    meta = generate_config_metadata()
    for m in meta:
        assert "section" in m, f"Field {m['name']} missing section"
        assert m["section"] != "unknown", f"Field {m['name']} has unknown section"


def test_descriptions_present() -> None:
    meta = generate_config_metadata()
    for m in meta:
        desc = m.get("description", "")
        assert desc, f"Field {m['name']} missing description"
        assert desc != "No description available.", (
            f"Field {m['name']} has placeholder description"
        )


def test_all_fields_have_help_plain() -> None:
    # Regression for PET-88: every config field ships with a real plain-language
    # help text — distinct from the technical description, never whitespace-only.
    for name, entry_meta in _FIELD_META.items():
        help_plain = entry_meta.get("help_plain", "")
        assert help_plain.strip(), f"Field {name!r} missing help_plain in _FIELD_META"
        assert help_plain.strip() != entry_meta["description"].strip(), (
            f"Field {name!r} help_plain duplicates its description"
        )
    for m in generate_config_metadata():
        help_plain = m.get("help_plain", "")
        assert help_plain.strip(), f"Field {m['name']} missing help_plain in metadata"
        assert help_plain != "No description available.", (
            f"Field {m['name']} has placeholder help_plain"
        )


def test_help_plain_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for PET-88: a _FIELD_META entry without help_plain falls back
    # to its description in the generated metadata.
    monkeypatch.setitem(
        _FIELD_META,
        "normalize_nfkc",
        {"description": "Technical text only.", "section": "normalization"},
    )
    by_name = {m["name"]: m for m in generate_config_metadata()}
    assert by_name["normalize_nfkc"]["help_plain"] == "Technical text only."
    assert by_name["normalize_nfkc"]["help_plain"]

    # Regression for PET-88: an empty-string help_plain falls back too, rather
    # than propagating an empty tip to the UI.
    monkeypatch.setitem(
        _FIELD_META,
        "normalize_nfkc",
        {"description": "Technical text only.", "help_plain": "", "section": "normalization"},
    )
    by_name = {m["name"]: m for m in generate_config_metadata()}
    assert by_name["normalize_nfkc"]["help_plain"] == "Technical text only."


# ── PET-114: section-level registry metadata ──────────────────────────────────


def test_every_field_section_has_registry_entry() -> None:
    # Brief-required: no field references a section the registry doesn't define
    # (prevents an orphan field section).
    registry_keys = {s["key"] for s in generate_section_metadata()}
    for entry in generate_config_metadata():
        assert entry["section"] in registry_keys, (
            f"Field {entry['name']!r} section {entry['section']!r} has no registry entry"
        )


def test_section_registry_frozen_and_ordered() -> None:
    # Brief-required: registry is immutable and deterministically ordered.
    # Frozen: instances reject attribute assignment; the registry is a tuple.
    section = _SECTION_REGISTRY[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        section.label = "mutated"  # type: ignore[misc]
    assert isinstance(_SECTION_REGISTRY, tuple)

    # Defensive copy: fresh list of fresh dicts each call; mutating one return
    # value cannot corrupt the source.
    a = generate_section_metadata()
    b = generate_section_metadata()
    assert a == b
    assert a is not b
    assert a[0] is not b[0]
    a[0]["label"] = "MUTATED"
    assert generate_section_metadata()[0]["label"] != "MUTATED"

    # Ordered: contiguous, 0-based, strictly increasing `order`; key sequence
    # matches the canonical order; deterministic across calls.
    sections = generate_section_metadata()
    assert [s["order"] for s in sections] == list(range(len(sections)))
    assert [s["key"] for s in sections] == _EXPECTED_SECTION_ORDER
    assert [s["key"] for s in generate_section_metadata()] == _EXPECTED_SECTION_ORDER

    # Open-first coupling: the open sections are exactly the leading five.
    assert [s["key"] for s in sections if not s["default_collapsed"]] == [
        s["key"] for s in sections
    ][:5]

    # Exact coverage (no drift): registry keys == the in-use field sections —
    # kills both a missing registry entry and a dead registry entry with no fields.
    assert {s["key"] for s in generate_section_metadata()} == {
        f["section"] for f in generate_config_metadata()
    }


def test_advanced_sections_default_collapsed() -> None:
    # Brief-required: advanced sections carry the collapsed flag; common ones open.
    by_key = {s["key"]: s for s in generate_section_metadata()}
    for key in _ADVANCED_SECTIONS:
        assert by_key[key]["default_collapsed"] is True, f"{key} should default collapsed"
    for key in _COMMON_SECTIONS:
        assert by_key[key]["default_collapsed"] is False, f"{key} should default open"


def test_section_metadata_entry_shape() -> None:
    # Every section dict has exactly the expected keys with the expected types.
    for s in generate_section_metadata():
        assert set(s.keys()) == {"key", "label", "description", "default_collapsed", "order"}
        assert isinstance(s["key"], str) and s["key"]
        assert isinstance(s["label"], str) and s["label"].strip()
        assert isinstance(s["description"], str) and s["description"].strip()
        assert isinstance(s["default_collapsed"], bool)
        assert isinstance(s["order"], int)


def test_config_section_is_frozen_slots_dataclass() -> None:
    # ConfigSection is a frozen, slotted dataclass (the "Frozen exports" invariant).
    assert dataclasses.is_dataclass(ConfigSection)
    params = ConfigSection.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True
    # slots=True means no per-instance __dict__.
    assert not hasattr(ConfigSection("k", "l", "d", default_collapsed=False), "__dict__")
