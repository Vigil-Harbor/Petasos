from __future__ import annotations

from types import MappingProxyType

from petasos.scanners.minimal import (
    _ALL_INJECTION_IDS,
    _ENCODING_RULE_IDS,
    _STRUCTURAL_RULE_IDS,
)
from petasos.session.profiles import (
    _BUILTIN_NAMES,
    _UNSUPPRESSIBLE_RULE_IDS,
    ProfileResolver,
    ResolvedProfile,
    _merge_with_base,
    _parse_profile,
)


class TestParseProfileStrips:
    def test_parse_profile_strips_injection_rules(self) -> None:
        data = {
            "name": "evil",
            "suppress_rules": list(_ALL_INJECTION_IDS),
        }
        profile = _parse_profile(data)
        assert profile.suppress_rules & _ALL_INJECTION_IDS == frozenset()

    def test_parse_profile_strips_structural_rules(self) -> None:
        data = {
            "name": "evil",
            "suppress_rules": list(_STRUCTURAL_RULE_IDS),
        }
        profile = _parse_profile(data)
        assert profile.suppress_rules & _STRUCTURAL_RULE_IDS == frozenset()


class TestMergeStrips:
    def test_merge_strips_injection_rules(self) -> None:
        resolver = ProfileResolver()
        base = resolver.resolve("general")
        overrides = {"suppress_rules": list(_ALL_INJECTION_IDS)}
        merged = _merge_with_base(base, overrides)
        assert merged.suppress_rules & _ALL_INJECTION_IDS == frozenset()


class TestEncodingStillSuppressible:
    def test_encoding_rules_still_suppressible(self) -> None:
        data = {
            "name": "permissive",
            "suppress_rules": list(_ENCODING_RULE_IDS),
        }
        profile = _parse_profile(data)
        assert profile.suppress_rules == _ENCODING_RULE_IDS

    def test_mixed_suppress_keeps_allowed(self) -> None:
        mixed = list(_ALL_INJECTION_IDS) + list(_ENCODING_RULE_IDS)
        data = {
            "name": "mixed",
            "suppress_rules": mixed,
        }
        profile = _parse_profile(data)
        assert profile.suppress_rules == _ENCODING_RULE_IDS


class TestDirectConstructionStrips:
    def test_direct_resolved_profile_strips(self) -> None:
        profile = ResolvedProfile(
            name="bypass",
            suppress_rules=frozenset(_ALL_INJECTION_IDS),
            severity_overrides=MappingProxyType({}),
            confidence_floor=0.0,
            tier_thresholds=None,
            pii_entities_extra=(),
            tool_exempt_list=frozenset(),
            tool_alias_map=MappingProxyType({}),
        )
        assert profile.suppress_rules & _ALL_INJECTION_IDS == frozenset()


class TestBuiltinProfilesClean:
    def test_builtin_profiles_no_unsuppressible(self) -> None:
        resolver = ProfileResolver()
        for name in _BUILTIN_NAMES:
            profile = resolver.resolve(name)
            overlap = profile.suppress_rules & _UNSUPPRESSIBLE_RULE_IDS
            assert overlap == frozenset(), (
                f"Built-in profile {name!r} has unsuppressible rules: {sorted(overlap)}"
            )
