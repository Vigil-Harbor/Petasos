"""Strength-preset registry for the Console Config Editor "tuning dial" (PET-124).

A strength preset is a coherent bundle of *existing* config-level strictness
fields that an operator can apply with one click, without knowing the individual
knobs. The five built-ins form a "metals temper" scale ordered soft to strict:
Tin, Bronze, Iron, Steel, Titanium. A sixth visible state, Custom, is *derived*
(see ``resolve_active_preset``) and is not a registry entry.

This module mirrors the ``_config_meta.py`` section-registry shape: a frozen
tuple of frozen dataclasses plus a ``generate_*_metadata()`` exporter that
returns a fresh list of fresh plain dicts each call. It adds no new config field,
no new apply path, and no enforcement floor: a preset only ever *sets* fields
that already exist on ``PetasosConfig``, so it is structurally incapable of
reaching either the Tier-3 terminate floor or the unsuppressible-rule floor
(both live below the config layer). See the PET-124 spec, Decisions D1-D9.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos.config import PetasosConfig

# D8: the preset-owned field set. Exactly these 11 config-level *strictness*
# fields participate in every preset bundle and in the Custom comparator.
# Deliberately excluded: the scanner circuit-breaker timing fields (reliability,
# not strictness) and the profile-axis levers (`confidence_floor`,
# `suppress_rules`), which are not config fields at all. `profile_name` is
# excluded too (D3) so the strength axis and scenario axis cannot shadow each
# other in the comparator.
_PRESET_OWNED_FIELDS: Final[frozenset[str]] = frozenset(
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
        "decode_encoded_payloads",
    }
)


@dataclass(frozen=True, slots=True)
class StrengthPreset:
    """One built-in strength level (a "metals temper" rung).

    Frozen + slotted (the project's frozen-exports invariant); ``overrides`` is
    a ``MappingProxyType`` so the bundle cannot be mutated in place. ``overrides``
    holds exactly the keys in ``_PRESET_OWNED_FIELDS`` (no more, no less), so the
    comparator is symmetric and unambiguous.
    """

    key: str  # "tin" | "bronze" | "iron" | "steel" | "titanium"
    label: str  # "Tin" .. "Titanium"
    order: int  # 0..4, ascending soft -> strict
    description: str  # short posture summary (tooltip source)
    overrides: Mapping[str, bool | float | str]


def _preset(
    key: str,
    label: str,
    order: int,
    description: str,
    overrides: dict[str, bool | float | str],
) -> StrengthPreset:
    """Build a StrengthPreset with an immutable overrides mapping."""
    return StrengthPreset(
        key=key,
        label=label,
        order=order,
        description=description,
        overrides=MappingProxyType(dict(overrides)),
    )


# D7: the five bundles. Lower tier thresholds escalate sooner (stricter); lower
# presidio_score_threshold matches more PII (stricter); fail_mode open < degraded
# < closed. Iron equals today's PetasosConfig defaults field-for-field (D6), so a
# fresh install resolves to Iron with zero behavior change. Every float literal
# below is the same decimal literal as the corresponding config default where
# they coincide (Iron's tiers 15/30/50, presidio 0.35), so the IEEE-754 doubles
# are identical and the Custom comparator's `==` is exact. The three core
# canonicalization toggles (normalize_nfkc / strip_zero_width / map_homoglyphs)
# stay on at every level; only Tin relaxes the higher-false-positive transforms.
#
# Floors are test-pinned regardless of these numbers: tier3 >= 30.0 (Titanium
# sits exactly at the floor) and no field here can carry a rule-suppression lever.
_PRESET_REGISTRY: Final[tuple[StrengthPreset, ...]] = (
    _preset(
        "tin",
        "Tin",
        0,
        "Loosest temper. Fail-open if an ML scanner breaks, tool-call guard off, "
        "and the higher-false-positive encoded-payload decode relaxed. "
        "Escalates latest. The always-on syntactic pre-filter "
        "still runs and Tier-3 still terminates at the floor.",
        {
            "fail_mode": "open",
            "tier1_threshold": 40.0,
            "tier2_threshold": 60.0,
            "tier3_threshold": 80.0,
            "presidio_score_threshold": 0.60,
            "anonymize": False,
            "tool_guard_enabled": False,
            "normalize_nfkc": True,
            "strip_zero_width": True,
            "map_homoglyphs": True,
            "decode_encoded_payloads": False,
        },
    ),
    _preset(
        "bronze",
        "Bronze",
        1,
        "Relaxed temper. Fail-degraded, tool-call guard on, full normalization. "
        "Escalates later than the default for noisier, lower-stakes workloads.",
        {
            "fail_mode": "degraded",
            "tier1_threshold": 25.0,
            "tier2_threshold": 45.0,
            "tier3_threshold": 65.0,
            "presidio_score_threshold": 0.50,
            "anonymize": False,
            "tool_guard_enabled": True,
            "normalize_nfkc": True,
            "strip_zero_width": True,
            "map_homoglyphs": True,
            "decode_encoded_payloads": True,
        },
    ),
    _preset(
        "iron",
        "Iron",
        2,
        "Balanced default temper, equal to the shipped config defaults: "
        "fail-degraded, full normalization, tool-call guard on. Recommended with "
        "the code_generation profile for coding agents.",
        {
            "fail_mode": "degraded",
            "tier1_threshold": 15.0,
            "tier2_threshold": 30.0,
            "tier3_threshold": 50.0,
            "presidio_score_threshold": 0.35,
            "anonymize": False,
            "tool_guard_enabled": True,
            "normalize_nfkc": True,
            "strip_zero_width": True,
            "map_homoglyphs": True,
            "decode_encoded_payloads": True,
        },
    ),
    _preset(
        "steel",
        "Steel",
        3,
        "Strict temper. Fail-closed, PII anonymization on, earlier escalation, "
        "and tighter PII sensitivity. A safe posture for handling third-party data.",
        {
            "fail_mode": "closed",
            "tier1_threshold": 10.0,
            "tier2_threshold": 22.0,
            "tier3_threshold": 40.0,
            "presidio_score_threshold": 0.30,
            "anonymize": True,
            "tool_guard_enabled": True,
            "normalize_nfkc": True,
            "strip_zero_width": True,
            "map_homoglyphs": True,
            "decode_encoded_payloads": True,
        },
    ),
    _preset(
        "titanium",
        "Titanium",
        4,
        "Strictest temper. Fail-closed, anonymization on, earliest escalation, "
        "and Tier-3 at the hard floor (30). Maximum teeth for high-stakes deployments.",
        {
            "fail_mode": "closed",
            "tier1_threshold": 8.0,
            "tier2_threshold": 18.0,
            "tier3_threshold": 30.0,
            "presidio_score_threshold": 0.25,
            "anonymize": True,
            "tool_guard_enabled": True,
            "normalize_nfkc": True,
            "strip_zero_width": True,
            "map_homoglyphs": True,
            "decode_encoded_payloads": True,
        },
    ),
)


def generate_preset_metadata() -> list[dict[str, Any]]:
    """Ordered strength-preset display metadata for the Config Editor dial.

    Returns a fresh list of fresh dicts each call (defensive copy — the registry
    source stays immutable). ``overrides`` is copied to a plain ``dict`` so no
    caller can mutate the frozen ``MappingProxyType``. Mirrors
    ``generate_section_metadata()``.
    """
    return [
        {
            "key": p.key,
            "label": p.label,
            "order": p.order,
            "description": p.description,
            "overrides": dict(p.overrides),
        }
        for p in _PRESET_REGISTRY
    ]


def resolve_active_preset(config: PetasosConfig | dict[str, Any]) -> str | None:
    """Return the key of the preset whose bundle the config currently matches.

    Projects ``config`` to ``_PRESET_OWNED_FIELDS`` and returns the unique
    ``preset.key`` whose ``overrides`` equals that projection, or ``None`` when
    none match (the derived **Custom** state, D5). There is no stored "is_custom"
    flag, so the dial can never drift out of sync with the actual config.

    Accepts a ``PetasosConfig`` (its ``to_dict()`` is called) or an already-built
    config dict (e.g. a redacted payload). No owned field is a secret, so a
    redacted dict resolves identically to the live object. A dict missing an
    owned key resolves to ``None`` rather than raising.
    """
    if isinstance(config, dict):
        config_dict: dict[str, Any] = config
    else:
        config_dict = config.to_dict()

    try:
        projection = {field: config_dict[field] for field in _PRESET_OWNED_FIELDS}
    except (KeyError, TypeError):
        return None

    for preset in _PRESET_REGISTRY:
        if dict(preset.overrides) == projection:
            return preset.key
    return None


__all__ = [
    "StrengthPreset",
    "generate_preset_metadata",
    "resolve_active_preset",
]
