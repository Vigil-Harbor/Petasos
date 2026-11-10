"""Roles, levels, and the one resolution from a settings document to a config.

A role says what the agent does. A level says how strict the checks are.
The two touch different fields, so the order between them does not matter.
``resolve`` merges defaults, then the role, then the level, then overrides,
and validates once.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from petasos.config.schema import ConfigError, from_mapping, leaves, merge, to_mapping
from petasos.config.sections import PetasosConfig

# A role may set only these leaves. A level may set only the others.
# The two sets are disjoint; a test keeps every built-in inside its set.
ROLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "rules.suppress",
        "rules.severity_overrides",
        "rules.confidence_floor",
        "rules.injection_floor_scope",
        "tools.dangerous_posture",
        "tools.exempt",
        "tools.aliases",
        "scanners.presidio.entities_extra",
    }
)
LEVEL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "fail_mode",
        "escalation.tier1",
        "escalation.tier2",
        "escalation.tier3",
        "scanners.presidio.score_threshold",
        "anonymization.enabled",
    }
)

# Old profile names a settings screen might still send.
_ROLE_ALIASES: Final[dict[str, str]] = {
    "code_generation": "coding",
    "customer_service": "support",
}
_LEVEL_ALIASES: Final[dict[str, str]] = {
    "bronze": "relaxed",
    "iron": "balanced",
    "steel": "strict",
}
_RETIRED_LEVELS: Final[dict[str, str]] = {
    "tin": "Tin is not a level. Set fail mode, the tool guard, and payload decoding in overrides.",
    "titanium": "Titanium is not a level. Set the stricter numbers in overrides.",
}

_SETTINGS_FIELDS: Final[tuple[str, ...]] = ("enabled", "role", "level", "overrides")
_EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})


def _copy_tree(value: object, *, prefix: str = "") -> Any:
    """A deep copy whose mappings and lists cannot be mutated by the caller."""
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ConfigError(((prefix, "a setting name must be text"),))
            child = f"{prefix}.{key}" if prefix else key
            copied[key] = _copy_tree(item, prefix=child)
        return MappingProxyType(copied)
    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
        return tuple(_copy_tree(item, prefix=prefix) for item in value)
    return value


def _document(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = _copy_tree(raw)
    if not isinstance(frozen, Mapping):
        raise TypeError("a layer document must be a mapping")
    return frozen


def document_fields(doc: Mapping[str, Any]) -> frozenset[str]:
    """The leaf paths a partial document sets.

    A mapping that is itself a leaf, such as severity overrides, is not walked
    into. A path that is neither a known leaf nor a parent of one is returned
    as itself so a test can see it.
    """
    known = ROLE_FIELDS | LEVEL_FIELDS
    found: set[str] = set()

    def walk(node: object, prefix: str) -> None:
        if prefix in known:
            found.add(prefix)
            return
        if isinstance(node, Mapping):
            for key, value in node.items():
                if type(key) is not str:
                    found.add(prefix or "<key>")
                    continue
                child = f"{prefix}.{key}" if prefix else key
                walk(value, child)
            return
        if prefix:
            found.add(prefix)

    walk(doc, "")
    return frozenset(found)


def contains(doc: Mapping[str, Any], path: str) -> bool:
    """True when ``path`` is present, including when its value is nothing."""
    node: object = doc
    parts = path.split(".")
    for index, part in enumerate(parts):
        if not isinstance(node, Mapping) or part not in node:
            return False
        if index == len(parts) - 1:
            return True
        node = node[part]
    return False


def _nearest(word: str, names: tuple[str, ...], aliases: Mapping[str, str]) -> str | None:
    aliased = aliases.get(word)
    if aliased is not None:
        return aliased
    folded = word.casefold()
    for name in names:
        if name != word and name.casefold() == folded:
            return name
    best_score = 0.0
    best: list[str] = []
    for name in names:
        score = difflib.SequenceMatcher(None, folded, name.casefold()).ratio()
        if score > best_score:
            best_score = score
            best = [name]
        elif score == best_score:
            best.append(name)
    if best_score < 0.6 or not best:
        return None
    return best[0]


def _unknown_name(
    kind: str, value: str, names: tuple[str, ...], aliases: Mapping[str, str]
) -> str:
    listed = ", ".join(names)
    retired = _RETIRED_LEVELS.get(value) if kind == "level" else None
    suggestion = _nearest(value, names, aliases)
    if suggestion is not None:
        message = (
            f'unknown {kind} "{value}". Did you mean "{suggestion}"? Expected one of {listed}.'
        )
    else:
        message = f'unknown {kind} "{value}". Expected one of {listed}.'
    if retired is not None:
        message = f"{message} {retired}"
    return message


@dataclass(frozen=True, slots=True)
class Role:
    """What the agent does, as a partial document and a suggested level.

    ``suggests`` is a recommendation for a settings screen. Resolution never
    applies it. ``document`` touches only role-owned fields.
    """

    name: str
    description: str
    document: Mapping[str, Any]
    suggests: str


@dataclass(frozen=True, slots=True)
class Level:
    """How strict the checks are, as a partial document of the level-owned fields."""

    name: str
    description: str
    document: Mapping[str, Any]


def _role(
    name: str,
    description: str,
    suggests: str,
    document: dict[str, Any] | None = None,
) -> Role:
    return Role(
        name=name,
        description=description,
        document=_document({} if document is None else document),
        suggests=suggests,
    )


def _level(name: str, description: str, document: dict[str, Any]) -> Level:
    return Level(name=name, description=description, document=_document(document))


# Order is the order a settings screen should offer.
ROLES: Final[Mapping[str, Role]] = MappingProxyType(
    {
        role.name: role
        for role in (
            _role(
                "general",
                "Balanced default for a general-purpose agent. "
                "It runs every rule at standard sensitivity.",
                "balanced",
            ),
            _role(
                "coding",
                "Tuned for a coding agent on the operator's own machine. "
                "It quiets rules that fire on ordinary code, "
                "and a dangerous tool call waits for approval.",
                "balanced",
                {
                    "rules": {
                        "suppress": [
                            "petasos.syntactic.encoding.invisible-chars",
                            "petasos.syntactic.encoding.base64-in-text",
                            "petasos.syntactic.encoding.homoglyph-substitution",
                            "petasos.syntactic.encoding.rtl-override",
                            "petasos.syntactic.command.pipe-to-shell",
                            "petasos.syntactic.injection.ignore-previous",
                            "petasos.syntactic.injection.ignore-all",
                            "petasos.syntactic.injection.disregard",
                            "petasos.syntactic.injection.new-instructions",
                            "petasos.syntactic.injection.system-override",
                            "petasos.syntactic.injection.system-prefix",
                            "petasos.syntactic.injection.inst-delimiter",
                            "petasos.syntactic.injection.you-are-now",
                            "petasos.syntactic.injection.role-switch-capability",
                            "petasos.syntactic.injection.role-switch-only",
                            "petasos.syntactic.injection.agent-directed-fetch",
                        ],
                        "severity_overrides": {"petasos.promptguard.injection": "low"},
                        "confidence_floor": 0.6,
                        "injection_floor_scope": "inbound",
                    },
                    "tools": {"dangerous_posture": "approve"},
                },
            ),
            _role(
                "research",
                "Low-friction for long research and browsing sessions. "
                "It quiets encoding rules that trip on quoted web pages "
                "and ignores low-confidence findings.",
                "relaxed",
                {
                    "rules": {
                        "suppress": [
                            "petasos.syntactic.encoding.invisible-chars",
                            "petasos.syntactic.encoding.base64-in-text",
                            "petasos.syntactic.encoding.homoglyph-substitution",
                            "petasos.syntactic.encoding.rtl-override",
                        ],
                        "confidence_floor": 0.7,
                    }
                },
            ),
            _role(
                "support",
                "Hardened for a user-facing support agent. "
                "It treats the common injection openers as critical "
                "and watches for names, emails, and phone numbers.",
                "balanced",
                {
                    "rules": {
                        "severity_overrides": {
                            "petasos.syntactic.injection.ignore-previous": "critical",
                            "petasos.syntactic.injection.ignore-all": "critical",
                            "petasos.syntactic.injection.disregard": "critical",
                            "petasos.syntactic.injection.you-are-now": "critical",
                            "petasos.syntactic.injection.new-instructions": "critical",
                            "petasos.syntactic.injection.system-override": "critical",
                        }
                    },
                    "scanners": {
                        "presidio": {
                            "entities_extra": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"],
                        }
                    },
                },
            ),
            _role(
                "admin",
                "Strict posture for a privileged or admin agent. "
                "It watches for names, emails, phone numbers, cards, and account numbers.",
                "strict",
                {
                    "scanners": {
                        "presidio": {
                            "entities_extra": [
                                "PERSON",
                                "EMAIL_ADDRESS",
                                "PHONE_NUMBER",
                                "CREDIT_CARD",
                                "IBAN_CODE",
                            ],
                        }
                    }
                },
            ),
        )
    }
)

LEVELS: Final[Mapping[str, Level]] = MappingProxyType(
    {
        level.name: level
        for level in (
            _level(
                "relaxed",
                "Fail-degraded, with later escalation, for noisier and lower-stakes work.",
                {
                    "fail_mode": "degraded",
                    "escalation": {"tier1": 25.0, "tier2": 45.0, "tier3": 65.0},
                    "scanners": {"presidio": {"score_threshold": 0.5}},
                    "anonymization": {"enabled": False},
                },
            ),
            _level(
                "balanced",
                "The shipped default: fail-degraded, standard escalation, "
                "and the standard personal-information threshold.",
                {
                    "fail_mode": "degraded",
                    "escalation": {"tier1": 15.0, "tier2": 30.0, "tier3": 50.0},
                    "scanners": {"presidio": {"score_threshold": 0.35}},
                    "anonymization": {"enabled": False},
                },
            ),
            _level(
                "strict",
                "Fail-closed, with earlier escalation and personal-information hiding turned on.",
                {
                    "fail_mode": "closed",
                    "escalation": {"tier1": 10.0, "tier2": 22.0, "tier3": 40.0},
                    "scanners": {"presidio": {"score_threshold": 0.3}},
                    "anonymization": {"enabled": True},
                },
            ),
        )
    }
)

ROLE_NAMES: Final[tuple[str, ...]] = tuple(ROLES)
LEVEL_NAMES: Final[tuple[str, ...]] = tuple(LEVELS)

# profile_name in a 0.5 section, renamed to a role.
PROFILE_TO_ROLE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "general": "general",
        "code_generation": "coding",
        "customer_service": "support",
        "research": "research",
        "admin": "admin",
    }
)


@dataclass(frozen=True, slots=True)
class Settings:
    """What a user writes: the arm switch, a role, a level, and any overrides.

    ``enabled`` is read live and is not part of ``PetasosConfig``. An empty
    ``overrides`` mapping means the role and level stand as they are.
    """

    enabled: bool = True
    role: str = "general"
    level: str = "balanced"
    overrides: Mapping[str, Any] = field(default_factory=lambda: _EMPTY)

    def __post_init__(self) -> None:
        problems: list[tuple[str, str]] = []
        if type(self.enabled) is not bool:
            problems.append(("enabled", "must be true or false"))
        if type(self.role) is not str or self.role.strip() == "":
            problems.append(("role", "must be text"))
        if type(self.level) is not str or self.level.strip() == "":
            problems.append(("level", "must be text"))
        if not isinstance(self.overrides, Mapping):
            problems.append(("overrides", "must be a group of settings"))
        if problems:
            raise ConfigError(problems)
        object.__setattr__(self, "overrides", _copy_tree(self.overrides, prefix="overrides"))


# The four settings a host stores. The manifest and the docs read this map.
SETTING_HELP: Final[Mapping[str, str]] = MappingProxyType(
    {
        "enabled": (
            "Whether Petasos enforces on this profile. Off lets tool calls through "
            "and records that they bypassed enforcement."
        ),
        "role": "What the agent does. A role sets the checks that belong to the job.",
        "level": ("How strict the checks are. A level sets fail mode, escalation, and hiding."),
        "overrides": (
            "Settings that replace what the role and level resolved to. "
            "A JSON object whose keys are config paths."
        ),
    }
)


@dataclass(frozen=True, slots=True)
class Resolved:
    """One settings document resolved to a config, with the source of each value.

    ``origin`` maps every leaf path to ``default``, ``role``, ``level``, or
    ``override``. The last layer whose document contains the path wins. A
    non-empty ``settings.overrides`` is what a screen calls custom.
    """

    settings: Settings
    config: PetasosConfig
    origin: Mapping[str, str]


def _as_settings(settings: Mapping[str, Any] | Settings) -> Settings:
    if isinstance(settings, Settings):
        return settings
    if not isinstance(settings, Mapping):
        raise ConfigError("settings must be a group of named values")
    problems: list[tuple[str, str]] = []
    clean: dict[str, Any] = {}
    for key, value in settings.items():
        if type(key) is not str:
            problems.append(("", "a setting name must be text"))
            continue
        if key not in _SETTINGS_FIELDS:
            suggestion = _nearest(key, _SETTINGS_FIELDS, {})
            if suggestion is not None:
                message = f'unknown setting "{key}". Did you mean "{suggestion}"?'
            else:
                listed = ", ".join(_SETTINGS_FIELDS)
                message = f'unknown setting "{key}". Expected one of {listed}.'
            problems.append((key, message))
            continue
        clean[key] = value
    if problems:
        raise ConfigError(problems)
    return Settings(
        enabled=clean.get("enabled", True),
        role=clean.get("role", "general"),
        level=clean.get("level", "balanced"),
        overrides=clean.get("overrides", {}),
    )


def _origins(
    role_doc: Mapping[str, Any],
    level_doc: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> Mapping[str, str]:
    origin: dict[str, str] = {}
    for info in leaves(PetasosConfig):
        source = "default"
        if contains(role_doc, info.path):
            source = "role"
        if contains(level_doc, info.path):
            source = "level"
        if contains(overrides, info.path):
            source = "override"
        origin[info.path] = source
    return MappingProxyType(origin)


def _prefix_overrides(exc: ConfigError) -> ConfigError:
    # Built-in roles and levels are valid together, so a failure is the overrides.
    pairs = tuple(
        (f"overrides.{path}" if path else "overrides", message) for path, message in exc.errors
    )
    return ConfigError(pairs)


def resolve(settings: Mapping[str, Any] | Settings) -> Resolved:
    """Merge defaults, role, level, and overrides, then validate once.

    An unknown role or level names the valid choices and the nearest name.
    A bad override is reported at the path the user typed, under ``overrides``.
    """
    chosen = _as_settings(settings)
    problems: list[tuple[str, str]] = []
    role = ROLES.get(chosen.role)
    level = LEVELS.get(chosen.level)
    if role is None:
        problems.append(("role", _unknown_name("role", chosen.role, ROLE_NAMES, _ROLE_ALIASES)))
    if level is None:
        problems.append(
            ("level", _unknown_name("level", chosen.level, LEVEL_NAMES, _LEVEL_ALIASES))
        )
    if problems or role is None or level is None:
        raise ConfigError(problems or (("role", "unknown role"),))
    merged = merge(to_mapping(PetasosConfig()), role.document)
    merged = merge(merged, level.document)
    merged = merge(merged, chosen.overrides)
    try:
        config = from_mapping(PetasosConfig, merged)
    except ConfigError as exc:
        raise _prefix_overrides(exc) from None
    return Resolved(
        settings=chosen,
        config=config,
        origin=_origins(role.document, level.document, chosen.overrides),
    )
