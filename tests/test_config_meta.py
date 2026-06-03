"""Tests for petasos.console._config_meta."""

import dataclasses

from petasos.config import _SECRET_FIELDS, PetasosConfig
from petasos.console._config_meta import generate_config_metadata


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
