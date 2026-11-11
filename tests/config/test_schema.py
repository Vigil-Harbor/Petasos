"""Behaviour of the declarative config schema engine."""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from typing import Any, Literal

import pytest

from petasos.config.schema import (
    ConfigError,
    FieldInfo,
    FieldSpec,
    SectionInfo,
    describe,
    from_mapping,
    merge,
    section,
    setting,
    to_mapping,
)

_S = Any
_TIER3_FLOOR = 30.0


def construct(cls: Callable[..., _S], /, **kwargs: Any) -> _S:
    return cls(**kwargs)


def construct_positional(cls: Callable[..., _S], /, *args: Any) -> _S:
    return cls(*args)


def leaves(cls: type[object]) -> dict[str, FieldInfo]:
    return {row.path: row for row in describe(cls) if isinstance(row, FieldInfo)}


def direct_children(rows: tuple[FieldInfo | SectionInfo, ...], parent: str) -> list[str]:
    """Paths of the rows one level under ``parent``, using only ``describe`` output."""
    prefix = f"{parent}." if parent else ""
    found: list[str] = []
    for row in rows:
        if parent and not row.path.startswith(prefix):
            continue
        rest = row.path[len(prefix) :]
        if rest and "." not in rest:
            found.append(row.path)
    return found


def problems(fn: Callable[[], object]) -> tuple[tuple[str, str], ...]:
    with pytest.raises(ConfigError) as caught:
        fn()
    return caught.value.errors


# Executed sections are real module globals, which is all annotation
# resolution can see. Names used in an annotation have to be placed here.
_DEFINITIONS = types.ModuleType("tests.config._schema_definitions")
sys.modules[_DEFINITIONS.__name__] = _DEFINITIONS
_DEFINITIONS.__dict__.update(
    {
        "ConfigError": ConfigError,
        "Literal": Literal,
        "Mapping": Mapping,
        "section": section,
        "setting": setting,
    }
)


def define(source: str) -> None:
    exec(source, _DEFINITIONS.__dict__)


@section
class EscalationLevels:
    """Strictly ascending tiers. The last tier has a hard floor."""

    tier1: float = setting(default=15.0, gt=0, help="Risk score at which tier 1 starts.")
    tier2: float = setting(default=30.0, gt=0, help="Risk score at which tier 2 starts.")
    tier3: float = setting(
        default=50.0,
        ge=_TIER3_FLOOR,
        help="Risk score at which the session is terminated.",
    )

    def check(self) -> None:
        if not self.tier1 < self.tier2 < self.tier3:
            raise ConfigError("tiers must be strictly ascending")


@section
class AlertLimits:
    """One count must not exceed another."""

    rapid_fire_count: int = setting(default=10, gt=0, help="How many events count as rapid fire.")
    ring_capacity: int = setting(default=1000, gt=0, help="How many recent events are kept.")

    def check(self) -> None:
        if self.rapid_fire_count > self.ring_capacity:
            raise ConfigError.at(
                "rapid_fire_count",
                "must not be higher than the ring capacity",
            )


@section
class NameLists:
    """Text lists with and without a per-item normaliser, plus an optional list."""

    scanners: tuple[str, ...] = setting(default=(), help="Scanner ids to leave unbuilt.")
    entities: tuple[str, ...] = setting(
        default=(),
        help="Entity names, stored in upper case.",
        normalize=str.upper,
    )
    extra_entities: tuple[str, ...] | None = setting(
        default=None,
        help="Extra entity names, or nothing to add none.",
        normalize=str.upper,
    )

    def check(self) -> None:
        if self.extra_entities is not None and len(self.extra_entities) == 0:
            raise ConfigError.at(
                "extra_entities",
                "must list at least one name when it is set",
            )


@section
class FrequencyWeights:
    """A mapping of names to non-negative finite weights."""

    weights: Mapping[str, float] | None = setting(
        default=None,
        ge=0,
        help="How much each severity adds to the running score.",
    )


@section
class SamplePolicy:
    """One example of every supported leaf, plus the cross-field samples."""

    enabled: bool = setting(default=True, help="Turn the policy on.", audience="basic")
    mode: Literal["open", "closed", "degraded"] = setting(
        default="degraded",
        help="What happens when a scanner breaks.",
    )
    limit: int = setting(default=8, ge=1, le=64, help="How many items to keep.")
    timeout: float = setting(
        default=10.0,
        gt=0,
        le=60,
        help="How long to wait, in seconds.",
        restart=True,
    )
    label: str | None = setting(default=None, help="Optional display name.")
    aliases: Mapping[str, str] = setting(default={}, help="Tool name aliases.")
    escalation: EscalationLevels = setting(default=EscalationLevels(), help="Tier thresholds.")
    alerts: AlertLimits = setting(default=AlertLimits(), help="Alert limits.")
    names: NameLists = setting(default=NameLists(), help="Name lists.")
    frequency: FrequencyWeights = setting(default=FrequencyWeights(), help="Frequency weights.")


def _typed_sample() -> SamplePolicy:
    return SamplePolicy(
        enabled=False,
        mode="closed",
        limit=4,
        timeout=5,
        label="lab",
        aliases={"run": "execute"},
        escalation=EscalationLevels(tier1=12.0, tier2=24.0, tier3=40.0),
        alerts=AlertLimits(rapid_fire_count=5, ring_capacity=20),
        names=NameLists(scanners=("semgrep",), entities=("url",), extra_entities=("email",)),
        frequency=FrequencyWeights(weights={"critical": 1.0}),
    )


class TestConstruction:
    def test_typed_constructor_and_equality(self) -> None:
        made = _typed_sample()
        assert made == from_mapping(SamplePolicy, to_mapping(made))
        assert made.escalation.tier1 == 12.0
        assert type(made.escalation.tier1) is float
        assert made.names.entities == ("URL",)
        assert made.names.extra_entities == ("EMAIL",)
        assert made.frequency.weights == {"critical": 1.0}

    def test_positional_construction_is_rejected(self) -> None:
        with pytest.raises(TypeError, match=r"keyword arguments only \(tier1, tier2, tier3\)"):
            construct_positional(EscalationLevels, 12.0, 24.0, 40.0)

    def test_both_routes_report_the_same_problems(self) -> None:
        payload = {"tier1": True, "tier3": 10}
        direct = problems(lambda: construct(EscalationLevels, **payload))
        mapped = problems(lambda: from_mapping(EscalationLevels, payload))
        assert direct == mapped
        assert direct == (
            ("tier1", "must be a finite number greater than 0 (not true or false), got true"),
            ("tier3", "must be a finite number at least 30, got 10"),
        )

    def test_bool_rejects_other_types(self) -> None:
        assert problems(lambda: construct(SamplePolicy, enabled=1)) == (
            ("enabled", "must be true or false, got 1"),
        )
        assert problems(lambda: from_mapping(SamplePolicy, {"enabled": "true"})) == (
            ("enabled", 'must be true or false, got "true"'),
        )

    def test_int_rejects_bool_and_fraction_and_enforces_bounds(self) -> None:
        assert problems(lambda: construct(SamplePolicy, limit=True)) == (
            (
                "limit",
                "must be a whole number at least 1 and at most 64 (not true or false), got true",
            ),
        )
        assert problems(lambda: construct(SamplePolicy, limit=1.5)) == (
            ("limit", "must be a whole number at least 1 and at most 64, got 1.5"),
        )
        assert problems(lambda: construct(AlertLimits, rapid_fire_count=0)) == (
            ("rapid_fire_count", "must be a whole number greater than 0, got 0"),
        )
        assert AlertLimits(rapid_fire_count=1).rapid_fire_count == 1

    def test_float_accepts_int_stores_float_and_rejects_non_finite(self) -> None:
        made = EscalationLevels(tier1=12, tier2=24, tier3=40)
        assert made.tier1 == 12.0
        assert type(made.tier1) is float
        assert problems(lambda: construct(SamplePolicy, timeout=0)) == (
            ("timeout", "must be a finite number greater than 0 and at most 60, got 0"),
        )
        assert problems(lambda: construct(SamplePolicy, timeout=float("inf"))) == (
            ("timeout", "must be a finite number greater than 0 and at most 60, got infinity"),
        )
        assert problems(lambda: construct(SamplePolicy, timeout=float("nan"))) == (
            (
                "timeout",
                "must be a finite number greater than 0 and at most 60, "
                "got a value that is not a number",
            ),
        )
        assert problems(lambda: construct(EscalationLevels, tier1=True)) == (
            ("tier1", "must be a finite number greater than 0 (not true or false), got true"),
        )

    def test_choice_rejects_a_different_case(self) -> None:
        assert problems(lambda: construct(SamplePolicy, mode="Open")) == (
            ("mode", 'must be exactly one of "open", "closed", or "degraded", got "Open"'),
        )
        assert from_mapping(SamplePolicy, {"mode": "closed"}).mode == "closed"

    def test_optional_text_accepts_nothing(self) -> None:
        assert SamplePolicy().label is None
        assert SamplePolicy(label="lab").label == "lab"
        assert problems(lambda: construct(SamplePolicy, label=1)) == (
            ("label", "must be text, or nothing, got 1"),
        )

    def test_string_list_rejects_a_bare_string_and_trims(self) -> None:
        assert problems(lambda: construct(NameLists, scanners="semgrep")) == (
            ("scanners", 'must be a list of text values, not a single text value, got "semgrep"'),
        )
        assert problems(lambda: from_mapping(NameLists, {"scanners": "semgrep"}))[0][0] == (
            "scanners"
        )
        made = construct(NameLists, scanners=[" semgrep ", "presidio"])
        assert made.scanners == ("semgrep", "presidio")
        assert problems(lambda: construct(NameLists, scanners=["ok", "  ", 4])) == (
            ("scanners[1]", "must not be empty"),
            ("scanners[2]", "must be text, got 4"),
        )
        assert problems(lambda: construct(NameLists, scanners=3)) == (
            ("scanners", "must be a list of text values, got 3"),
        )

    def test_normaliser_runs_per_item_after_trimming(self) -> None:
        made = from_mapping(NameLists, {"entities": [" url ", "Email"]})
        assert made.entities == ("URL", "EMAIL")

    def test_optional_list_must_be_non_empty_when_present(self) -> None:
        assert NameLists().extra_entities is None
        assert construct(NameLists, extra_entities=["email"]).extra_entities == ("EMAIL",)
        assert problems(lambda: NameLists(extra_entities=())) == (
            ("extra_entities", "must list at least one name when it is set"),
        )
        assert problems(lambda: from_mapping(NameLists, {"extra_entities": []})) == (
            ("extra_entities", "must list at least one name when it is set"),
        )

    def test_weight_mapping_rules(self) -> None:
        made = FrequencyWeights(weights={" critical ": 1, "high": 0})
        assert made.weights == {"critical": 1.0, "high": 0.0}
        assert type(made.weights["critical"]) is float
        assert problems(lambda: construct(FrequencyWeights, weights=["no"])) == (
            ("weights", "must be a group of named values, or nothing, got a list"),
        )
        assert problems(lambda: construct(FrequencyWeights, weights={"": 1})) == (
            ("weights", "each name must not be empty"),
        )
        assert problems(lambda: construct(FrequencyWeights, weights={"a": 1, " a ": 2})) == (
            ("weights", 'the name "a" is repeated'),
        )
        assert problems(lambda: construct(FrequencyWeights, weights={"low": -1})) == (
            ("weights.low", "must be a finite number at least 0, got -1"),
        )
        assert problems(lambda: construct(FrequencyWeights, weights={"low": True})) == (
            ("weights.low", "must be a finite number at least 0 (not true or false), got true"),
        )
        nan_weight = problems(lambda: construct(FrequencyWeights, weights={"low": float("nan")}))
        assert nan_weight == (
            (
                "weights.low",
                "must be a finite number at least 0, got a value that is not a number",
            ),
        )
        assert problems(lambda: construct(SamplePolicy, aliases={"tool": 1})) == (
            ("aliases.tool", "must be text, got 1"),
        )

    def test_ascending_tiers_and_floor(self) -> None:
        assert problems(lambda: EscalationLevels(tier1=40, tier2=30, tier3=50)) == (
            ("", "tiers must be strictly ascending"),
        )
        assert problems(lambda: from_mapping(EscalationLevels, {"tier3": 29})) == (
            ("tier3", "must be a finite number at least 30, got 29"),
        )

    def test_one_field_must_not_exceed_another(self) -> None:
        assert problems(lambda: AlertLimits(rapid_fire_count=5, ring_capacity=4)) == (
            ("rapid_fire_count", "must not be higher than the ring capacity"),
        )
        assert AlertLimits(rapid_fire_count=4, ring_capacity=4).rapid_fire_count == 4


class TestAggregation:
    def test_every_problem_is_reported_with_its_path(self) -> None:
        document = {
            "enabled": 1,
            "mode": "Open",
            "escalation": {"tier1": "bad", "tier2": 40, "tier3": 10, "tyer2": 1},
            "alerts": {"rapid_fire_count": 5, "ring_capacity": 4},
            "lable": True,
        }
        found = problems(lambda: from_mapping(SamplePolicy, document))
        assert found == (
            ("lable", 'unknown setting "lable". Did you mean "label"?'),
            ("enabled", "must be true or false, got 1"),
            ("mode", 'must be exactly one of "open", "closed", or "degraded", got "Open"'),
            ("escalation.tyer2", 'unknown setting "tyer2". Did you mean "tier2"?'),
            ("escalation.tier1", 'must be a finite number greater than 0, got "bad"'),
            ("escalation.tier3", "must be a finite number at least 30, got 10"),
            ("alerts.rapid_fire_count", "must not be higher than the ring capacity"),
        )
        assert "strictly ascending" not in str(found)

    def test_direct_nested_mapping_uses_the_same_paths(self) -> None:
        found = problems(
            lambda: construct(
                SamplePolicy,
                escalation={"tier1": "bad", "tyer2": 1},
            )
        )
        assert ("escalation.tyer2", 'unknown setting "tyer2". Did you mean "tier2"?') in found
        assert ("escalation.tier1", 'must be a finite number greater than 0, got "bad"') in found

    def test_a_failed_field_skips_that_sections_check(self) -> None:
        found = problems(lambda: construct(EscalationLevels, tier1="no", tier2=40, tier3=50))
        assert found == (("tier1", 'must be a finite number greater than 0, got "no"'),)
        assert "ascending" not in found[0][1]

    def test_a_nested_check_is_prefixed_and_blocks_the_parent_check(self) -> None:
        @section
        class Parent:
            alerts: AlertLimits = setting(default=AlertLimits(), help="Alert limits.")

            def check(self) -> None:
                if self.alerts.ring_capacity < 10:
                    raise ConfigError("parent hook")

        found = problems(
            lambda: from_mapping(
                Parent,
                {"alerts": {"rapid_fire_count": 5, "ring_capacity": 4}},
            )
        )
        assert found == (("alerts.rapid_fire_count", "must not be higher than the ring capacity"),)
        assert "parent hook" not in str(ConfigError(found))
        parent_only = problems(
            lambda: from_mapping(
                Parent,
                {"alerts": {"rapid_fire_count": 3, "ring_capacity": 4}},
            )
        )
        assert parent_only == (("", "parent hook"),)

    def test_unknown_key_without_a_close_name(self) -> None:
        found = problems(lambda: from_mapping(EscalationLevels, {"xyzzy": 1}))
        assert found == (
            ("xyzzy", 'unknown setting "xyzzy". Expected one of tier1, tier2, tier3.'),
        )
        assert "Did you mean" not in found[0][1]

    def test_suggestion_ignores_case(self) -> None:
        found = problems(lambda: from_mapping(SamplePolicy, {"Enabled": False}))
        assert found[0] == ("Enabled", 'unknown setting "Enabled". Did you mean "enabled"?')

    def test_a_document_must_be_a_mapping(self) -> None:
        document: Any = ["no"]
        assert problems(lambda: from_mapping(SamplePolicy, document)) == (
            ("", "settings must be a group of named values, got a list"),
        )

    def test_a_setting_name_must_be_text(self) -> None:
        document: Any = {1: True}
        assert problems(lambda: from_mapping(SamplePolicy, document)) == (
            ("", "a setting name must be text, got 1"),
        )

    def test_error_text_includes_the_path(self) -> None:
        error = ConfigError.at("tier3", "must be at least 30")
        assert error.errors == (("tier3", "must be at least 30"),)
        assert str(error) == "tier3: must be at least 30"
        assert ConfigError("tiers must be strictly ascending").errors == (
            ("", "tiers must be strictly ascending"),
        )


class TestDescribeAndRoundTrip:
    def test_describe_lists_sections_and_leaves_in_order(self) -> None:
        rows = describe(SamplePolicy)
        by_path = leaves(SamplePolicy)
        assert [row.path for row in rows][:4] == ["enabled", "mode", "limit", "timeout"]
        escalation = rows[[row.path for row in rows].index("escalation")]
        assert isinstance(escalation, SectionInfo)
        assert escalation.help == "Tier thresholds."
        assert escalation.audience == "advanced"
        assert escalation.restart is False
        assert escalation.nullable is False
        assert direct_children(rows, "") == [
            "enabled",
            "mode",
            "limit",
            "timeout",
            "label",
            "aliases",
            "escalation",
            "alerts",
            "names",
            "frequency",
        ]
        assert direct_children(rows, "escalation") == [
            "escalation.tier1",
            "escalation.tier2",
            "escalation.tier3",
        ]
        assert direct_children(rows, "names") == [
            "names.scanners",
            "names.entities",
            "names.extra_entities",
        ]
        assert rows.index(escalation) < [row.path for row in rows].index("escalation.tier1")
        assert by_path["escalation.tier3"].ge == 30.0
        assert by_path["escalation.tier3"].type_name == "float"
        assert by_path["escalation.tier1"].default == 15.0
        assert by_path["mode"].type_name == "choice"
        assert by_path["mode"].choices == ("open", "closed", "degraded")
        assert by_path["mode"].default == "degraded"
        assert by_path["enabled"].choices is None
        assert by_path["enabled"].audience == "basic"
        assert by_path["timeout"].restart is True
        assert by_path["timeout"].audience == "advanced"
        assert by_path["names.scanners"].type_name == "tuple[str, ...]"
        assert by_path["names.scanners"].default == []
        assert by_path["names.extra_entities"].nullable is True
        assert by_path["frequency.weights"].type_name == "mapping[str, float]"
        assert by_path["frequency.weights"].nullable is True
        assert by_path["frequency.weights"].ge == 0.0
        assert by_path["aliases"].type_name == "mapping[str, str]"
        assert by_path["label"].nullable is True
        assert by_path["limit"].help == "How many items to keep."
        for row in rows:
            if isinstance(row, FieldInfo):
                json.dumps(row.default)
                if row.choices is not None:
                    json.dumps(list(row.choices))

    def test_describe_uses_an_overridden_nested_default(self) -> None:
        @section
        class Parent:
            escalation: EscalationLevels = setting(
                default=EscalationLevels(tier1=12.0, tier2=24.0, tier3=40.0),
                help="Tier thresholds.",
                audience="expert",
                restart=True,
            )

        rows = leaves(Parent)
        assert rows["escalation.tier1"].default == 12.0
        described = describe(Parent)
        section_row = described[0]
        assert isinstance(section_row, SectionInfo)
        assert section_row.path == "escalation"
        assert section_row.help == "Tier thresholds."
        assert section_row.audience == "expert"
        assert section_row.restart is True
        assert Parent().escalation.tier1 == 12.0

    def test_describe_nests_a_section_under_its_parent(self) -> None:
        @section
        class Holder:
            policy: SamplePolicy | None = setting(default=None, help="The whole policy.")

        rows = describe(Holder)
        policy = rows[0]
        assert isinstance(policy, SectionInfo)
        assert policy.path == "policy"
        assert policy.help == "The whole policy."
        assert policy.nullable is True
        assert direct_children(rows, "") == ["policy"]
        assert "policy.escalation" in direct_children(rows, "policy")
        assert direct_children(rows, "policy.escalation") == [
            "policy.escalation.tier1",
            "policy.escalation.tier2",
            "policy.escalation.tier3",
        ]
        nested = rows[[row.path for row in rows].index("policy.escalation")]
        assert isinstance(nested, SectionInfo)
        assert nested.help == "Tier thresholds."
        assert leaves(Holder)["policy.escalation.tier1"].default == 15.0

    def test_round_trip_is_json_and_equal(self) -> None:
        original = _typed_sample()
        plain = to_mapping(original)
        assert plain["names"]["scanners"] == ["semgrep"]
        assert plain["names"]["entities"] == ["URL"]
        assert plain["frequency"]["weights"] == {"critical": 1.0}
        assert plain["aliases"] == {"run": "execute"}
        restored = from_mapping(SamplePolicy, json.loads(json.dumps(plain)))
        assert restored == original

    def test_field_spec_is_on_the_dataclass_field(self) -> None:
        spec = fields(EscalationLevels)[2].metadata[FieldSpec]
        assert isinstance(spec, FieldSpec)
        assert spec.ge == 30.0
        assert spec.help.startswith("Risk score")


class TestMerge:
    def test_mappings_merge_and_other_values_replace(self) -> None:
        assert merge(
            {"escalation": {"tier1": 15, "tier2": 30}, "names": ["a", "b"]},
            {"escalation": {"tier2": 40}, "names": ["c"]},
        ) == {"escalation": {"tier1": 15, "tier2": 40}, "names": ["c"]}

    def test_explicit_none_replaces_and_a_missing_key_does_not(self) -> None:
        assert merge({"label": "x", "mode": "open"}, {"mode": "closed"}) == {
            "label": "x",
            "mode": "closed",
        }
        assert merge({"label": "x"}, {"label": None}) == {"label": None}
        assert merge({"weights": {"a": 1}}, {"weights": None}) == {"weights": None}

    def test_an_empty_mapping_changes_nothing(self) -> None:
        assert merge({"weights": {"a": 1}}, {"weights": {}}) == {"weights": {"a": 1}}
        assert merge({"weights": {"a": 1}}, {}) == {"weights": {"a": 1}}

    def test_result_does_not_share_containers(self) -> None:
        base = {"names": ["a"], "group": {"k": 1}}
        result = merge(base, {})
        result["names"].append("b")
        result["group"]["k"] = 9
        assert base == {"names": ["a"], "group": {"k": 1}}


class TestImmutability:
    def test_instances_are_frozen_slotted_dataclasses(self) -> None:
        made = SamplePolicy()
        assert is_dataclass(made)
        assert not hasattr(made, "__dict__")
        with pytest.raises(FrozenInstanceError):
            _assign(made, "enabled", False)
        assert [item.name for item in fields(EscalationLevels)] == ["tier1", "tier2", "tier3"]

    def test_replace_revalidates(self) -> None:
        original = EscalationLevels()
        updated = replace(original, tier1=16.0)
        assert updated.tier1 == 16.0
        assert original.tier1 == 15.0
        assert problems(lambda: replace(original, tier1=40.0, tier2=30.0, tier3=50.0)) == (
            ("", "tiers must be strictly ascending"),
        )

    def test_lists_and_mappings_are_copied(self) -> None:
        raw_names = [" semgrep ", "presidio"]
        made = construct(NameLists, scanners=raw_names)
        raw_names.append("extra")
        raw_names[0] = "changed"
        assert made.scanners == ("semgrep", "presidio")
        with pytest.raises(TypeError):
            _assign_item(made.scanners, 0, "other")

        raw_weights = {"critical": 1}
        weighted = construct(FrequencyWeights, weights=raw_weights)
        raw_weights["critical"] = 9
        assert weighted.weights == {"critical": 1.0}
        with pytest.raises(TypeError):
            _assign_key(weighted.weights, "critical", 2.0)

    def test_a_dict_default_is_not_shared_with_the_caller(self) -> None:
        raw = {"critical": 1.0}

        @section
        class Box:
            weights: Mapping[str, float] = setting(default=raw, ge=0, help="Weights.")

        raw["critical"] = 9.0
        assert Box().weights["critical"] == 1.0
        with pytest.raises(TypeError):
            _assign_key(Box().weights, "critical", 2.0)

    def test_a_list_default_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="immutable"):
            setting(default=[], help="Names.")


class TestDefinition:
    def test_unsupported_annotations_fail_at_definition(self) -> None:
        cases = {
            "raw: bytes = setting(default=b'abc', help='Raw.')": "bytes",
            "names: list[str] = setting(default=(), help='Names.')": "tuple\\[str, \\.\\.\\.\\]",
            "table: dict[str, float] = setting(default={}, help='Table.')": "Mapping",
            "nums: tuple[int, ...] = setting(default=(), help='Nums.')": "not a supported",
            "flags: Mapping[str, int] = setting(default={}, help='Flags.')": "not a supported",
            "value: int | str = setting(default=1, help='Value.')": "one supported type",
        }
        for body, match in cases.items():
            with pytest.raises(TypeError, match=match):
                define(f"@section\nclass Bad:\n    {body}\n")

    def test_a_plain_class_is_not_a_section(self) -> None:
        with pytest.raises(TypeError, match="Nested groups"):
            define(
                """
class Plain:
    pass

@section
class Bad:
    child: Plain = setting(default=Plain(), help="Child.")
"""
            )

    def test_bounds_and_normaliser_must_match_the_type(self) -> None:
        with pytest.raises(TypeError, match="bounds"):
            define(
                "@section\nclass Bad:\n"
                "    flag: bool = setting(default=True, ge=0, help='Flag.')\n"
            )
        with pytest.raises(TypeError, match="normalize"):
            define(
                "@section\nclass Bad:\n"
                "    count: int = setting(default=1, help='Count.', normalize=str.upper)\n"
            )

    def test_impossible_bounds_and_invalid_defaults(self) -> None:
        with pytest.raises(TypeError, match="no valid number"):
            setting(default=1, ge=5, le=4, help="Count.")
        with pytest.raises(TypeError, match="default is not valid"):
            define(
                "@section\nclass Bad:\n    count: int = setting(default=0, gt=0, help='Count.')\n"
            )
        with pytest.raises(TypeError, match="defaults are not valid"):
            define(
                """
@section
class Bad:
    low: float = setting(default=30.0, gt=0, help="Low.")
    high: float = setting(default=10.0, gt=0, help="High.")
    def check(self) -> None:
        if not self.low < self.high:
            raise ConfigError("low must be below high")
"""
            )

    def test_hand_written_post_init_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="__post_init__"):
            define(
                """
@section
class Bad:
    n: int = setting(default=1, help="Count.")
    def __post_init__(self) -> None:
        return None
"""
            )

    def test_help_must_not_be_empty(self) -> None:
        with pytest.raises(TypeError, match="help"):
            setting(default=True, help="")
        with pytest.raises(TypeError, match="help"):
            setting(default=True, help="   ")

    def test_an_undefined_annotation_says_to_import_it_at_runtime(self) -> None:
        with pytest.raises(TypeError, match="Import the name at runtime") as caught:
            define(
                """
from __future__ import annotations

@section
class Bad:
    labels: Sequence[str] = setting(default=(), help="Labels.")
"""
            )
        message = str(caught.value)
        assert "Sequence" in message
        assert "not defined" in message

    def test_a_normaliser_must_return_text(self) -> None:
        def bad(text: str) -> Any:
            return len(text)

        with pytest.raises(TypeError, match="normalize"):

            @section
            class Box:
                names: tuple[str, ...] = setting(default=(), help="Names.", normalize=bad)

            construct(Box, names=["ab"])


def _assign(obj: Any, name: str, value: object) -> None:
    setattr(obj, name, value)


def _assign_item(value: Any, index: int, item: object) -> None:
    value[index] = item


def _assign_key(value: Any, key: str, item: object) -> None:
    value[key] = item


class TestLabels:
    def test_label_and_choice_labels_reach_describe(self) -> None:
        @section
        class Labelled:
            mode: Literal["a", "b"] = setting(
                default="a",
                help="Pick one.",
                label="Mode",
                choice_labels={"a": "First", "b": "Second"},
            )
            plain_name: int = setting(default=1, help="A number.")

        rows = leaves(Labelled)
        assert rows["mode"].label == "Mode"
        assert rows["mode"].choice_labels == {"a": "First", "b": "Second"}
        assert rows["plain_name"].label == "Plain name"
        assert rows["plain_name"].choice_labels is None

    def test_choice_labels_must_cover_every_choice(self) -> None:
        with pytest.raises(TypeError, match="every choice"):

            @section
            class Partial:
                mode: Literal["a", "b"] = setting(
                    default="a", help="Pick one.", choice_labels={"a": "First"}
                )

    def test_choice_labels_apply_only_to_a_choice(self) -> None:
        with pytest.raises(TypeError, match="only to a choice"):

            @section
            class NotAChoice:
                count: int = setting(default=1, help="A number.", choice_labels={"1": "One"})

    def test_an_empty_label_is_refused(self) -> None:
        with pytest.raises(TypeError, match="label"):
            setting(default=1, help="A number.", label=" ")
