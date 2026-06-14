from __future__ import annotations

import logging
import subprocess
import sys
from types import MappingProxyType

import pytest

from petasos.config import TIER3_FLOOR
from petasos.scanners.minimal import _STRUCTURAL_RULE_IDS
from petasos.scanners.presidio import KNOWN_PII_ENTITIES
from petasos.session.profiles import (
    _BUILTIN_NAMES,
    ProfileResolver,
    ResolvedProfile,
    TierThresholds,
    _parse_profile,
)

# ---------------------------------------------------------------------------
# TierThresholds validation
# ---------------------------------------------------------------------------


class TestTierThresholds:
    def test_valid_ascending(self) -> None:
        tt = TierThresholds(tier1=5.0, tier2=15.0, tier3=35.0)
        assert tt.tier1 == 5.0
        assert tt.tier2 == 15.0
        assert tt.tier3 == 35.0

    def test_non_ascending_raises(self) -> None:
        with pytest.raises(ValueError, match="strictly ascending"):
            TierThresholds(tier1=10.0, tier2=10.0, tier3=35.0)

    def test_tier3_below_floor_raises(self) -> None:
        with pytest.raises(ValueError, match=f">= {TIER3_FLOOR}"):
            TierThresholds(tier1=1.0, tier2=2.0, tier3=3.0)

    def test_non_finite_raises(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            TierThresholds(tier1=float("inf"), tier2=20.0, tier3=35.0)

    def test_frozen(self) -> None:
        tt = TierThresholds(tier1=5.0, tier2=15.0, tier3=35.0)
        with pytest.raises(AttributeError):
            tt.tier1 = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ProfileResolver — loading & resolve
# ---------------------------------------------------------------------------


class TestProfileResolverLoading:
    def test_all_builtins_load(self) -> None:
        resolver = ProfileResolver()
        for name in _BUILTIN_NAMES:
            profile = resolver.resolve(name)
            assert isinstance(profile, ResolvedProfile)
            assert profile.name == name

    def test_general_profile_is_identity(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("general")
        assert p.suppress_rules == frozenset()
        assert dict(p.severity_overrides) == {}
        assert p.confidence_floor == 0.0
        assert p.tier_thresholds is None
        assert p.pii_entities_extra == ()
        assert p.tool_exempt_list == frozenset()
        assert dict(p.tool_alias_map) == {}

    def test_resolve_unknown_raises_keyerror(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(KeyError, match="nonexistent"):
            resolver.resolve("nonexistent")

    def test_admin_profile_values(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("admin")
        assert p.tier_thresholds is not None
        assert p.tier_thresholds.tier1 == 10.0
        assert p.tier_thresholds.tier2 == 20.0
        assert p.tier_thresholds.tier3 == 35.0
        assert "PERSON" in p.pii_entities_extra
        assert "CREDIT_CARD" in p.pii_entities_extra

    def test_research_profile_suppress_rules(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("research")
        assert "petasos.syntactic.encoding.invisible-chars" in p.suppress_rules
        assert "petasos.syntactic.injection.inst-delimiter" not in p.suppress_rules
        assert p.confidence_floor == 0.7
        assert p.tier_thresholds is not None
        assert p.tier_thresholds.tier1 == 25.0

    def test_code_generation_profile(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("code_generation")
        assert "petasos.syntactic.encoding.invisible-chars" in p.suppress_rules
        assert p.confidence_floor == 0.6

    def test_customer_service_severity_overrides(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("customer_service")
        assert len(p.severity_overrides) > 0
        assert "PERSON" in p.pii_entities_extra


# ---------------------------------------------------------------------------
# ProfileResolver — frozen & serialization
# ---------------------------------------------------------------------------


class TestProfileFrozenAndSerialization:
    def test_profile_is_frozen(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("general")
        with pytest.raises(AttributeError):
            p.name = "hacked"  # type: ignore[misc]

    def test_to_dict_roundtrip(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("admin")
        d = p.to_dict()
        assert d["name"] == "admin"
        assert isinstance(d["suppress_rules"], list)
        assert isinstance(d["severity_overrides"], dict)
        assert d["tier_thresholds"] is not None
        assert d["tier_thresholds"]["tier1"] == 10.0
        assert isinstance(d["pii_entities_extra"], list)
        assert isinstance(d["tool_exempt_list"], list)
        assert isinstance(d["tool_alias_map"], dict)

    def test_general_to_dict_null_thresholds(self) -> None:
        resolver = ProfileResolver()
        d = resolver.resolve("general").to_dict()
        assert d["tier_thresholds"] is None

    def test_empty_suppress_rules_roundtrip(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve("general")
        d = p.to_dict()
        assert d["suppress_rules"] == []


# ---------------------------------------------------------------------------
# ProfileResolver — register
# ---------------------------------------------------------------------------


class TestProfileRegister:
    def test_register_custom_profile(self) -> None:
        resolver = ProfileResolver()
        custom = ResolvedProfile(
            name="custom_test",
            suppress_rules=frozenset(["rule.a"]),
            severity_overrides=MappingProxyType({}),
            confidence_floor=0.5,
            tier_thresholds=None,
            pii_entities_extra=(),
            tool_exempt_list=frozenset(),
            tool_alias_map=MappingProxyType({}),
        )
        resolver.register("custom_test", custom)
        resolved = resolver.resolve("custom_test")
        assert resolved is custom
        assert resolved.name == "custom_test"

    def test_register_builtin_raises(self) -> None:
        resolver = ProfileResolver()
        custom = ResolvedProfile(
            name="general",
            suppress_rules=frozenset(["rule.x"]),
            severity_overrides=MappingProxyType({}),
            confidence_floor=0.99,
            tier_thresholds=None,
            pii_entities_extra=(),
            tool_exempt_list=frozenset(),
            tool_alias_map=MappingProxyType({}),
        )
        with pytest.raises(ValueError, match="Cannot overwrite built-in profile"):
            resolver.register("general", custom)


# ---------------------------------------------------------------------------
# Dict merge (custom profiles)
# ---------------------------------------------------------------------------


class TestDictMerge:
    def test_dict_merge_inherits_from_general(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve({"confidence_floor": 0.8})
        assert p.name == "custom"
        assert p.confidence_floor == 0.8
        assert p.suppress_rules == frozenset()

    def test_suppress_rules_union(self) -> None:
        resolver = ProfileResolver()
        general = resolver.resolve("general")
        base_suppress = general.suppress_rules
        p = resolver.resolve({"suppress_rules": ["rule.a", "rule.b"]})
        assert "rule.a" in p.suppress_rules
        assert "rule.b" in p.suppress_rules
        assert base_suppress.issubset(p.suppress_rules)

    def test_severity_overrides_merge(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve({"severity_overrides": {"rule.x": "critical"}})
        assert p.severity_overrides["rule.x"] == "critical"

    def test_tier_thresholds_override(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve({"tier_thresholds": {"tier1": 5.0, "tier2": 15.0, "tier3": 35.0}})
        assert p.tier_thresholds is not None
        assert p.tier_thresholds.tier1 == 5.0

    def test_tier_thresholds_partial_raises(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ValueError, match="all three keys"):
            resolver.resolve({"tier_thresholds": {"tier1": 5.0}})

    def test_tier_thresholds_none_override(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve({"tier_thresholds": None})
        assert p.tier_thresholds is None

    def test_pii_entities_union(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve({"pii_entities_extra": ["IBAN_CODE"]})
        assert "IBAN_CODE" in p.pii_entities_extra

    def test_tool_exempt_list_replace(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve({"tool_exempt_list": ["Read", "WRITE"]})
        assert "read" in p.tool_exempt_list
        assert "write" in p.tool_exempt_list

    def test_tool_alias_map_merge(self) -> None:
        resolver = ProfileResolver()
        p = resolver.resolve({"tool_alias_map": {"custom_tool": "mapped"}})
        assert p.tool_alias_map["custom_tool"] == "mapped"

    def test_tool_alias_map_empty_value_raises(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ValueError, match="non-empty"):
            resolver.resolve({"tool_alias_map": {"bad": ""}})

    def test_confidence_floor_type_error(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ValueError, match="number"):
            resolver.resolve({"confidence_floor": "high"})

    def test_suppress_rules_type_error(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ValueError, match="list"):
            resolver.resolve({"suppress_rules": "not_a_list"})

    def test_resolve_invalid_type_raises(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(TypeError, match="str or dict"):
            resolver.resolve(42)  # type: ignore[arg-type]

    def test_alias_onto_exempt_raises_at_parse(self) -> None:
        with pytest.raises(ValueError, match="cannot be exempt keys"):
            _parse_profile(
                {
                    "name": "evil",
                    "tool_alias_map": {"exec": "read"},
                    "tool_exempt_list": ["read"],
                }
            )

    def test_alias_onto_exempt_raises_at_parse_whitespace(self) -> None:
        with pytest.raises(ValueError, match="cannot be exempt keys"):
            _parse_profile(
                {
                    "name": "evil",
                    "tool_alias_map": {"exec": " read "},
                    "tool_exempt_list": ["read"],
                }
            )

    def test_alias_onto_exempt_raises_at_merge(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ValueError, match="cannot be exempt keys"):
            resolver.resolve(
                {
                    "tool_alias_map": {"exec": "read"},
                    "tool_exempt_list": ["read"],
                }
            )

    def test_alias_onto_exempt_raises_at_merge_whitespace(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ValueError, match="cannot be exempt keys"):
            resolver.resolve(
                {
                    "tool_alias_map": {"exec": " read "},
                    "tool_exempt_list": ["read"],
                }
            )


# ---------------------------------------------------------------------------
# PIPE-07: Structural rule override protection (PET-54)
# ---------------------------------------------------------------------------


class TestStructuralOverrideProtection:
    def test_structural_rule_override_rejected_at_parse(self) -> None:
        with pytest.raises(ValueError, match="structural rules"):
            _parse_profile(
                {
                    "name": "evil",
                    "severity_overrides": {
                        "petasos.syntactic.structural.oversized-payload": "info"
                    },
                }
            )

    def test_structural_rule_override_rejected_at_merge(self) -> None:
        resolver = ProfileResolver()
        with pytest.raises(ValueError, match="structural rules"):
            resolver.resolve(
                {"severity_overrides": {"petasos.syntactic.structural.binary-content": "info"}}
            )

    def test_structural_rule_ids_match_prefix(self) -> None:
        prefix = "petasos.syntactic.structural."
        for rule_id in _STRUCTURAL_RULE_IDS:
            assert rule_id.startswith(prefix), f"{rule_id} does not start with {prefix}"


# ---------------------------------------------------------------------------
# PET-113: Built-in profile descriptions
# ---------------------------------------------------------------------------


class TestProfileDescriptions:
    def test_builtin_profiles_have_descriptions(self) -> None:
        # Regression for PET-113: every built-in profile exposes a renderable,
        # non-empty description (catches "" / whitespace-only and a regression to
        # str(None) coercion), and the new field is frozen like the rest.
        resolver = ProfileResolver()
        for name in _BUILTIN_NAMES:
            p = resolver.resolve(name)
            assert p.description.strip(), f"{name} has empty description"
            assert p.description != "None", f"{name} description is str(None) garbage"
            with pytest.raises(AttributeError):
                p.description = "x"  # type: ignore[misc]

    def test_profile_description_roundtrips(self) -> None:
        # Regression for PET-113: description survives to_dict -> _parse_profile and
        # every branch of the resolved validation policy (Decision 5) holds.
        resolver = ProfileResolver()
        p = resolver.resolve("admin")
        assert _parse_profile(p.to_dict()).description == p.description

        # missing key -> "" (back-compat)
        assert _parse_profile({"name": "x"}).description == ""

        # present-but-non-string raises on the JSON path (None and 123 are
        # distinct isinstance branches)
        with pytest.raises(ValueError, match="must be a string"):
            _parse_profile({"name": "x", "description": None})
        with pytest.raises(ValueError, match="must be a string"):
            _parse_profile({"name": "x", "description": 123})

        # custom dict-merge override present
        assert resolver.resolve({"description": "mine"}).description == "mine"

        # custom override non-string raises on the merge path
        with pytest.raises(ValueError, match="must be a string"):
            resolver.resolve({"description": 123})

        # custom override absent does not inherit general's copy (Decision 2)
        assert resolver.resolve({"confidence_floor": 0.8}).description == ""


# ---------------------------------------------------------------------------
# PET-117: pii_entities_extra validation (dead EMAIL entity + typo guard)
# ---------------------------------------------------------------------------


# Zero-dep import-guard probe (test 6). A fresh interpreter imports the profile
# package and asserts neither Presidio package was pulled in transitively, then
# prints a positive verdict token. Fresh-interpreter isolation makes this robust
# even when Presidio is installed in the venv (which patch.dict(sys.modules, ...)
# cannot achieve). Mirrors the subprocess-probe idiom in
# tests/test_llama_firewall_wrapper.py.
_PROBE_SRC = r"""
import sys
import petasos.session.profiles  # noqa: F401
assert "presidio_analyzer" not in sys.modules, "presidio_analyzer was imported"
assert "presidio_anonymizer" not in sys.modules, "presidio_anonymizer was imported"
print("OK")
"""


class TestPiiEntityValidation:
    def test_builtin_profiles_use_known_pii_entities(self) -> None:
        # Regression for PET-117: the assertion that would have caught the dead
        # EMAIL entity. Construction itself now enforces this via the strict parse
        # path; the explicit check documents intent and localizes the failure.
        resolver = ProfileResolver()
        for name in _BUILTIN_NAMES:
            p = resolver.resolve(name)
            for entity in p.pii_entities_extra:
                assert entity in KNOWN_PII_ENTITIES, f"{name} lists unknown pii entity {entity!r}"

    def test_no_builtin_profile_contains_bare_email(self) -> None:
        # Frozen-export pin (PET-117): bare EMAIL is dead (no recognizer); the
        # canonical name is EMAIL_ADDRESS. Re-fails the instant the typo returns.
        resolver = ProfileResolver()
        for name in _BUILTIN_NAMES:
            assert "EMAIL" not in resolver.resolve(name).pii_entities_extra
        assert "EMAIL_ADDRESS" in resolver.resolve("customer_service").pii_entities_extra
        assert "EMAIL_ADDRESS" in resolver.resolve("admin").pii_entities_extra

    def test_parse_profile_rejects_unknown_pii_entity(self) -> None:
        # Strict path (built-in parse): an unknown name raises ValueError.
        with pytest.raises(ValueError, match="unknown pii_entities_extra"):
            _parse_profile({"name": "x", "pii_entities_extra": ["EMAIL"]})
        # A valid recognizer name does not raise.
        _parse_profile({"name": "x", "pii_entities_extra": ["EMAIL_ADDRESS"]})
        # An unhashable malformed entry raises ValueError (the contracted type),
        # not TypeError — pins the isinstance-guarded membership check.
        with pytest.raises(ValueError, match="unknown pii_entities_extra"):
            _parse_profile({"name": "x", "pii_entities_extra": [["EMAIL"]]})

    def test_merge_warns_unknown_pii_entity_without_raising(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Lenient path (custom merge): an unknown name warns and is retained,
        # never raises.
        resolver = ProfileResolver()
        with caplog.at_level(logging.WARNING, logger="petasos.session.profiles"):
            p = resolver.resolve({"pii_entities_extra": ["EMAIL"]})
        assert "EMAIL" in p.pii_entities_extra
        assert any("unknown pii_entities_extra" in r.getMessage() for r in caplog.records)
        # A known name produces no warning.
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="petasos.session.profiles"):
            resolver.resolve({"pii_entities_extra": ["IBAN_CODE"]})
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_known_pii_entities_contents(self) -> None:
        for known in (
            "EMAIL_ADDRESS",
            "PERSON",
            "PHONE_NUMBER",
            "CREDIT_CARD",
            "IBAN_CODE",
            "URL",
        ):
            assert known in KNOWN_PII_ENTITIES
        assert "EMAIL" not in KNOWN_PII_ENTITIES

    def test_profiles_import_does_not_load_presidio(self) -> None:
        # Zero-dep guard (PET-117): importing the profile package must not pull in
        # presidio_analyzer/presidio_anonymizer (the validator imports only the
        # KNOWN_PII_ENTITIES constant, and every Presidio import in presidio.py is
        # deferred). Fresh-interpreter isolation via subprocess; the "OK" token is a
        # positive-evidence gate so a crashed/silent child cannot read as a pass.
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE_SRC],
            capture_output=True,
            text=True,
            timeout=60,  # trivial import probe; bound it so a regression can't hang the suite
        )
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout
