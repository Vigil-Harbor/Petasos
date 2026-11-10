"""Temporary bridge from a flat config and a profile to the config tree.

Deleted, with the flat config and the profiles package, once every caller
has moved. This is the only module that imports both. Field moves come from
``migrate.MOVES``. A profile's tier thresholds are not copied: the guard reads
the config tree's escalation tiers.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from petasos._types import severity_rank
from petasos.config import PetasosConfig
from petasos.config.floors import (
    INJECTION_PREFIX,
    KNOWN_PII_ENTITIES,
    SELFMOD_BASE_SEVERITY,
    SELFMOD_PREFIX,
    SEVERITY_NAMES,
    STRUCTURAL_PREFIX,
)
from petasos.config.migrate import MOVES, _get, _scanner_values, _set, canon
from petasos.config.schema import FieldInfo, from_mapping, leaves, to_mapping
from petasos.config.secrets import Secrets
from petasos.config.sections import PetasosConfig as TreeConfig

if TYPE_CHECKING:
    from petasos.session.profiles import (
        ProfileResolver as ProfileResolver,
    )
    from petasos.session.profiles import (
        ResolvedProfile as ResolvedProfile,
    )
    from petasos.session.profiles import (
        TierThresholds as TierThresholds,
    )

_logger = logging.getLogger(__name__)

FlatConfig = PetasosConfig

# A tree already holds the levers a profile used to set.
PROFILE_WITH_TREE = (
    "a config tree already carries the levers a profile used to set; do not pass a profile"
)

_ENTITY_EXTRA = "scanners.presidio.entities_extra"
_INFO: dict[str, FieldInfo] = {info.path: info for info in leaves(TreeConfig)}
_SEMGREP_FIELDS = (
    "semgrep_enabled",
    "semgrep_engine_path",
    "semgrep_engine_sha256",
    "semgrep_request_timeout_seconds",
    "semgrep_max_source_bytes",
)

ConfigInput = FlatConfig | TreeConfig


@dataclass(frozen=True, slots=True)
class Bound:
    """The tree a constructor keeps, the secrets beside it, and the flat object.

    ``legacy`` is None when the caller passed a tree. ``profile`` is the
    resolved profile whose levers were copied, or None when none applied.
    Tier thresholds on that profile are not copied.
    """

    config: TreeConfig
    secrets: Secrets
    legacy: FlatConfig | None
    profile: ResolvedProfile | None


def bind(
    config: ConfigInput | None = None,
    profile: str | ResolvedProfile | dict[str, Any] | None = None,
    *,
    secrets: Secrets | None = None,
    use_profile_name: bool = True,
) -> Bound:
    """Accept a flat config or a config tree, plus a profile in any old form.

    A missing config is the flat default. A tree and a profile together raise
    ``ValueError``. An explicit ``secrets`` replaces secrets taken from a flat
    config. Bad frequency weights raise the tracker's ``ValueError``.
    """
    if isinstance(config, TreeConfig):
        if profile is not None:
            raise ValueError(PROFILE_WITH_TREE)
        return Bound(
            config=config,
            secrets=secrets if secrets is not None else Secrets(),
            legacy=None,
            profile=None,
        )
    if config is None:
        config = FlatConfig()
    elif not isinstance(config, FlatConfig):
        raise TypeError(
            f"config must be a flat config or a config tree, got {type(config).__name__}"
        )
    resolved = _resolve_profile(profile, config, use_profile_name=use_profile_name)
    _reject_bad_weights(config.frequency_weights)
    tree = from_mapping(TreeConfig, _document(config, resolved))
    held = secrets if secrets is not None else _secrets_of(config)
    return Bound(config=tree, secrets=held, legacy=replace(config), profile=resolved)


def require_hash_key(config: TreeConfig, secrets: Secrets) -> None:
    """Reject hash-mode anonymization that has no hash key.

    The flat config enforced this on itself. The tree does not carry the key,
    so the check runs where a config and a ``Secrets`` meet.
    """
    anonymization = config.anonymization
    if anonymization.enabled and anonymization.mode == "hash" and not secrets.hash_key:
        raise ValueError(
            "hash_key is required and must be non-empty when "
            "redaction_mode='hash' and anonymize=True"
        )


def list_profiles() -> list[dict[str, Any]]:
    """The built-in profiles, as the resolver lists them."""
    from petasos.session.profiles import ProfileResolver

    return ProfileResolver().list_profiles()


def semgrep_settings_changed(live: FlatConfig, incoming: FlatConfig) -> bool:
    """True when a flat reconfigure would have ignored Semgrep settings."""
    if any(getattr(incoming, name) != getattr(live, name) for name in _SEMGREP_FIELDS):
        return True
    return ("semgrep" in incoming.disabled_scanners) != ("semgrep" in live.disabled_scanners)


def secret_change_ignored(live: FlatConfig, incoming: FlatConfig) -> bool:
    """True when an incoming flat config tries to replace a live session secret."""
    return incoming.session_secret is not None and incoming.session_secret != live.session_secret


def preserved_flat(live: FlatConfig, incoming: FlatConfig) -> FlatConfig:
    """The flat config a reconfigure stores.

    Semgrep fields stay at their live values. A Semgrep id in the live
    disabled list stays disabled. The live session secret is kept.
    """
    preserved = {name: getattr(live, name) for name in _SEMGREP_FIELDS}
    disabled = tuple(name for name in incoming.disabled_scanners if name != "semgrep")
    if "semgrep" in live.disabled_scanners:
        disabled = (*disabled, "semgrep")
    return replace(
        incoming,
        session_secret=live.session_secret,
        disabled_scanners=disabled,
        **preserved,
    )


def __getattr__(name: str) -> Any:
    if name in {"ProfileResolver", "ResolvedProfile", "TierThresholds"}:
        from petasos.session import profiles as profile_mod

        return getattr(profile_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _resolve_profile(
    profile: str | ResolvedProfile | dict[str, Any] | None,
    flat: FlatConfig,
    *,
    use_profile_name: bool,
) -> ResolvedProfile | None:
    from petasos.session.profiles import ProfileResolver, ResolvedProfile

    if isinstance(profile, ResolvedProfile):
        return profile
    resolver = ProfileResolver()
    if isinstance(profile, str):
        return resolver.resolve(profile)
    if isinstance(profile, dict):
        return resolver.resolve(profile)
    if profile is not None:
        raise TypeError(
            "profile must be a name, a resolved profile, or a mapping, "
            f"got {type(profile).__name__}"
        )
    if not use_profile_name or not flat.profile_name:
        return None
    return resolver.resolve(flat.profile_name)


def _secrets_of(flat: FlatConfig) -> Secrets:
    return Secrets(session_secret=flat.session_secret, hash_key=flat.hash_key)


def _reject_bad_weights(weights: object) -> None:
    """Raise the tracker's ``ValueError`` for a weight map the tree would reject.

    The flat config accepts a bad glob and the tracker rejects it at
    construction. Raising here keeps that error for a config that is bridged
    at construction.
    """
    if not isinstance(weights, Mapping):
        return
    for key, weight in weights.items():
        if type(key) is not str:
            continue
        if key.endswith(".*"):
            if "*" in key[:-2]:
                raise ValueError(f"glob key has '*' in non-terminal position: {key!r}")
        elif "*" in key:
            raise ValueError(f"weight key has '*' in non-terminal position: {key!r}")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            continue
        if weight < 0 or not math.isfinite(float(weight)):
            raise ValueError(f"weight must be non-negative and finite: {key!r}={weight!r}")


def _document(flat: FlatConfig, profile: ResolvedProfile | None) -> dict[str, Any]:
    raw = {move.old: getattr(flat, move.old) for move in MOVES if hasattr(flat, move.old)}
    document = to_mapping(TreeConfig())
    for move in MOVES:
        if move.kind != "leaf" or move.path is None or move.old not in raw:
            continue
        if move.path == _ENTITY_EXTRA:
            continue
        info = _INFO.get(move.path)
        if info is None:
            continue
        _set(document, move.path, _json(canon(info, raw[move.old])))
    for path, value in _scanner_values(raw, [], []).items():
        _set(document, path, value)
    _set(document, _ENTITY_EXTRA, _extras(flat, profile))
    _repair_entities(document)
    if profile is not None:
        _apply_profile(document, profile)
    return document


def _extras(flat: FlatConfig, profile: ResolvedProfile | None) -> list[str]:
    """Flat detection extras first, then profile extras that are not listed.

    Names the tree does not know are dropped. A custom profile already warned
    about those, and they never matched a recognizer.
    """
    names: list[str] = []
    seen: set[str] = set()
    sources: list[object] = [flat.presidio_entities_extra]
    if profile is not None:
        sources.append(profile.pii_entities_extra)
    for source in sources:
        if isinstance(source, str) or not isinstance(source, (list, tuple)):
            continue
        for item in source:
            if type(item) is not str:
                continue
            text = item.strip().upper()
            if not text or text in seen or text not in KNOWN_PII_ENTITIES:
                continue
            seen.add(text)
            names.append(text)
    return names


def _repair_entities(document: dict[str, Any]) -> None:
    """Drop wholesale entity names the tree rejects.

    The flat config accepts any token. An unknown name matches no recognizer
    in this package. An all-unknown list cannot be stored empty, so it is
    left unset, which is the curated default the scanner bootstrap still
    overrides from the flat config.
    """
    try:
        entities = _get(document, "scanners.presidio.entities")
    except KeyError:
        return
    if not isinstance(entities, list):
        return
    known = [name for name in entities if name in KNOWN_PII_ENTITIES]
    if len(known) != len(entities):
        _set(document, "scanners.presidio.entities", known or None)


def _apply_profile(document: dict[str, Any], profile: ResolvedProfile) -> None:
    floor = float(profile.confidence_floor)
    if floor < 0.0:
        floor = 0.0
    elif floor > 1.0:
        floor = 1.0
    _set(document, "rules.suppress", _suppressible(profile))
    _set(document, "rules.severity_overrides", _overrides(profile))
    _set(document, "rules.confidence_floor", floor)
    _set(document, "rules.injection_floor_scope", profile.injection_floor_scope)
    _set(document, "tools.dangerous_posture", profile.dangerous_tool_posture)
    _set(document, "tools.exempt", sorted(profile.tool_exempt_list))
    _set(document, "tools.aliases", _aliases(profile))


def _overrides(profile: ResolvedProfile) -> dict[str, str]:
    """Drop overrides the tree rejects and the scan used to ignore.

    A profile built directly can name a structural rule, a severity the scan
    does not know, or a self-modification rule below its recorded severity.
    The scan kept the finding's own severity in those cases.
    """
    known = set(SEVERITY_NAMES)
    kept: dict[str, str] = {}
    for rule_id, severity in profile.severity_overrides.items():
        if severity not in known or rule_id.startswith(STRUCTURAL_PREFIX):
            continue
        if rule_id.startswith(SELFMOD_PREFIX):
            base = SELFMOD_BASE_SEVERITY.get(rule_id)
            if base is None or severity_rank(severity) < severity_rank(base):
                continue
        kept[rule_id] = severity
    return kept


def _aliases(profile: ResolvedProfile) -> dict[str, str]:
    """Drop an alias whose target is exempt.

    A profile built directly can carry that collision. The guard used to keep
    the original tool name and log this warning at match time. Dropping the
    alias first lets the tree build and leaves the same name in place.
    """
    exempt = {name.casefold() for name in profile.tool_exempt_list}
    kept: dict[str, str] = {}
    for key, value in profile.tool_alias_map.items():
        target = value.strip().casefold()
        if target in exempt:
            _logger.warning(
                "profile alias %r -> %r blocked: target is exempt (GUARD-03)",
                key,
                value,
            )
            continue
        kept[key] = value
    return kept


def _suppressible(profile: ResolvedProfile) -> list[str]:
    """Drop rule ids the tree rejects and the profile parser kept.

    Real structural ids are already removed, with the same warning, when the
    profile is resolved. A prefix the tree refuses and the id set does not
    name is removed here so the old input still builds.
    """
    kept: list[str] = []
    blocked: list[str] = []
    for rule_id in sorted(profile.suppress_rules):
        structural = rule_id.startswith(STRUCTURAL_PREFIX)
        selfmod = rule_id.startswith(SELFMOD_PREFIX)
        injection = rule_id.startswith(INJECTION_PREFIX) and (
            profile.injection_floor_scope != "inbound"
        )
        if structural or selfmod or injection:
            blocked.append(rule_id)
        else:
            kept.append(rule_id)
    if blocked:
        _logger.warning(
            "suppress_rules attempted to suppress unsuppressible rules (stripped): %s",
            blocked,
        )
    return kept


def _json(value: object) -> object:
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items() if type(key) is str}
    return value


__all__ = [
    "PROFILE_WITH_TREE",
    "Bound",
    "ConfigInput",
    "FlatConfig",
    "PetasosConfig",
    "ProfileResolver",
    "ResolvedProfile",
    "Secrets",
    "TierThresholds",
    "bind",
    "list_profiles",
    "preserved_flat",
    "require_hash_key",
    "secret_change_ignored",
    "semgrep_settings_changed",
]
