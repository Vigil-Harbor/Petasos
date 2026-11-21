"""Rule levers: what may be dropped, retargeted, or ignored as too weak."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from petasos.config.floors import (
    INJECTION_PREFIX,
    SELFMOD_BASE_SEVERITY,
    SELFMOD_PREFIX,
    SEVERITY_NAMES,
    STRUCTURAL_PREFIX,
)
from petasos.config.schema import ConfigError, section, setting
from petasos.model import severity_rank

_SEVERITIES = frozenset(SEVERITY_NAMES)
_SEVERITY_LIST = ", ".join(SEVERITY_NAMES)


def _family(rule_id: str) -> str | None:
    if rule_id.startswith(STRUCTURAL_PREFIX):
        return "structural"
    if rule_id.startswith(SELFMOD_PREFIX):
        return "self-modification"
    if rule_id.startswith(INJECTION_PREFIX):
        return "injection"
    return None


@section
class RulesConfig:
    """Validate rule controls without weakening structural or self-change floors.

    A structural or self-modification rule cannot be suppressed. An injection
    rule can be suppressed only when the floor is limited to inbound text.
    A structural rule cannot be retargeted. A self-modification rule cannot
    be set below the severity the guard gives it."""

    suppress: tuple[str, ...] = setting(
        default=(),
        label="Rules turned off",
        help=(
            "Rules that are ignored completely: they do not block, are not recorded, "
            "and do not raise the risk score. One rule id per line. Rules that check "
            "the shape of the input, or changes to Petasos itself, cannot be turned off."
        ),
    )
    severity_overrides: Mapping[str, str] = setting(
        default={},
        label="Rules with a different severity",
        help=(
            "Make a rule count as more or less serious. Low and info findings are "
            "reported without blocking."
        ),
        entry_labels=("Rule id", "Severity"),
    )
    confidence_floor: float = setting(
        default=0.0,
        ge=0,
        le=1,
        label="Ignore weak matches below",
        help=(
            "Each finding carries a match strength from 0 to 1. Findings weaker than "
            "this are ignored. 0 keeps everything."
        ),
    )
    injection_floor_scope: Literal["all", "inbound"] = setting(
        default="all",
        label="Hidden-instruction rules can be turned off",
        help=(
            "Whether the rules for hidden instructions may be turned off for text the "
            "agent sends out. They always stay on for text coming in."
        ),
        choice_labels={
            "all": "Never: they stay on in both directions",
            "inbound": "Only for text going out",
        },
    )

    def check(self) -> None:
        """Reject suppressions and severity overrides that violate rule floors."""
        problems: list[tuple[str, str]] = []
        seen: set[str] = set()
        for index, rule_id in enumerate(self.suppress):
            path = f"suppress[{index}]"
            if rule_id in seen:
                problems.append((path, f'the rule "{rule_id}" is repeated'))
            seen.add(rule_id)
            family = _family(rule_id)
            if family in ("structural", "self-modification"):
                problems.append((path, f'"{rule_id}" is a {family} rule and cannot be suppressed'))
            elif family == "injection" and self.injection_floor_scope != "inbound":
                problems.append(
                    (
                        path,
                        f'"{rule_id}" can be suppressed only when the injection floor '
                        "is limited to inbound text",
                    )
                )
        for rule_id, severity in self.severity_overrides.items():
            path = f"severity_overrides.{rule_id}"
            if severity not in _SEVERITIES:
                problems.append((path, f"must be one of {_SEVERITY_LIST}"))
                continue
            family = _family(rule_id)
            if family == "structural":
                problems.append(
                    (path, f'"{rule_id}" is a structural rule and cannot be retargeted')
                )
                continue
            if family != "self-modification":
                continue
            base = SELFMOD_BASE_SEVERITY.get(rule_id)
            if base is None or severity_rank(severity) < severity_rank(base):
                floor = base if base is not None else "its recorded severity"
                problems.append((path, f'"{rule_id}" cannot be set below {floor}'))
        if problems:
            raise ConfigError(problems)
