"""Name the syntactic rules and their suppression floors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.scanners.minimal.command import _COMMAND_PATTERNS
from petasos.scanners.minimal.injection import _INJECTION_PATTERNS

if TYPE_CHECKING:
    from petasos.model import (
        Severity,
    )

    pass


from dataclasses import dataclass


@dataclass(frozen=True)
class SyntacticRule:
    rule_id: str
    category: str
    severity: Severity
    can_suppress: bool
    description: str


_AGENT_DIRECTIVE_RULE_IDS: frozenset[str] = frozenset(
    {"petasos.syntactic.injection.agent-directed-fetch"}
)

# --- Rule taxonomy ---

_INJECTION_RULE_IDS = frozenset(
    f"petasos.syntactic.injection.{slug}" for slug, _ in _INJECTION_PATTERNS
)

_ROLE_SWITCH_RULE_IDS = frozenset(
    [
        "petasos.syntactic.injection.role-switch-capability",
        "petasos.syntactic.injection.role-switch-only",
    ]
)

_STRUCTURAL_RULE_IDS = frozenset(
    [
        "petasos.syntactic.structural.oversized-payload",
        "petasos.syntactic.structural.excessive-depth",
        "petasos.syntactic.structural.binary-content",
    ]
)

_ENCODING_RULE_IDS = frozenset(
    [
        "petasos.syntactic.encoding.invisible-chars",
        "petasos.syntactic.encoding.base64-in-text",
        "petasos.syntactic.encoding.homoglyph-substitution",
        "petasos.syntactic.encoding.rtl-override",
    ]
)

_COMMAND_RULE_IDS: frozenset[str] = frozenset(
    f"petasos.syntactic.command.{slug}" for slug, _pattern, _confidence in _COMMAND_PATTERNS
)

RULE_TAXONOMY: frozenset[str] = (
    _INJECTION_RULE_IDS
    | _ROLE_SWITCH_RULE_IDS
    | _STRUCTURAL_RULE_IDS
    | _ENCODING_RULE_IDS
    | _COMMAND_RULE_IDS
    | _AGENT_DIRECTIVE_RULE_IDS  # PET-154
)

_ALL_INJECTION_IDS = (
    _INJECTION_RULE_IDS | _ROLE_SWITCH_RULE_IDS | _AGENT_DIRECTIVE_RULE_IDS  # PET-154
)

# The command family (_COMMAND_RULE_IDS, PET-94) is deliberately OUTSIDE this set
# — it is suppressible (Decision 1). The unsuppressible set exists to prevent
# profile-driven evasion of *injection detection* (SYN-08/PROF-04); command
# rules detect *content dangerous to execute*, not content that manipulates the
# model, and legitimate workloads (code generation) routinely emit it, so
# code_generation suppresses pipe-to-shell only and leaves the other four
# command rules active (PET-221). A future family-author who
# wants a non-suppressible command rule must re-decide this consciously.
_UNSUPPRESSIBLE_RULE_IDS = _STRUCTURAL_RULE_IDS | _ALL_INJECTION_IDS
