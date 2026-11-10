"""Rule levers: what may be dropped, retargeted, or ignored as too weak."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from petasos._types import severity_rank
from petasos.config.floors import (
    INJECTION_PREFIX,
    SELFMOD_BASE_SEVERITY,
    SELFMOD_PREFIX,
    SEVERITY_NAMES,
    STRUCTURAL_PREFIX,
)
from petasos.config.schema import ConfigError, section, setting

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
    """Which findings are dropped, retargeted, or ignored for being too weak.

    A structural or self-modification rule cannot be suppressed. An injection
    rule can be suppressed only when the floor is limited to inbound text.
    A structural rule cannot be retargeted. A self-modification rule cannot
    be set below the severity the guard gives it.
    """

    suppress: tuple[str, ...] = setting(
        default=(),
        help="Rule ids to drop before they affect the verdict, the audit, or escalation.",
    )
    severity_overrides: Mapping[str, str] = setting(
        default={},
        help="Change a rule's severity so a noisy rule can stay visible without blocking.",
    )
    confidence_floor: float = setting(
        default=0.0,
        ge=0,
        le=1,
        help="Ignore findings weaker than this confidence, from 0 to 1.",
    )
    injection_floor_scope: Literal["all", "inbound"] = setting(
        default="all",
        help="Keep injection rules mandatory on every direction, or only on text coming in.",
    )

    def check(self) -> None:
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
