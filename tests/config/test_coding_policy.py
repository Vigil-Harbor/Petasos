"""PET-135 regression corpus for the code_generation profile tuning.

Investigation summary (docs/specs/TODO/PET-135.*): an offline replay of the
operator's real Hermes tool-call corpus (state.db, 2460 unique calls) through
the Petasos pipeline showed that the deterministic MinimalScanner layer is
ALREADY clean under code_generation (zero blocking findings on routine coding).
The false positives that forced the live disarm came from the ML layer,
specifically PromptGuard's prompt-injection classifier (petasos.promptguard.injection),
which blocked ~6% of routine tool calls (ls, curl, git status, file searches over
the project's own security docs) at confidence 0.5-1.0. The 0.6 confidence_floor
could not tame it (5 of 6 scored >=0.7), so the tuning downgrades that one ML
rule to a non-blocking LOW via severity_overrides.

These tests pin BOTH sides of the recurring bug (brief "tests that prevent
recurrence"): the routine corpus must stay clean, and the genuine catches the
profile does NOT trade away (syntactic injection / role-switch / structural)
must keep firing at blocking severity. All deterministic: MinimalScanner only,
plus a stub scanner standing in for the (nondeterministic) ML backend.

Which test pins the actual fix (read first): the FP being fixed is the ML-layer
rule petasos.promptguard.injection. The deterministic corpus test wires no ML
scanner, so the corpus is clean both before and after the override; it is a
MinimalScanner floor guard, not the regression for the ML fix. The load-bearing
regression is the stub-driven test_ml_injection_is_nonblocking_under_codegen
(paired with ..._still_blocks_under_general): those fail before the override and
pass after. Round 2 added the escalation-bound, corpus-integrity, and
description-pin tests below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.config.layers import resolve
from petasos.scanners.minimal.taxonomy import (
    _ALL_INJECTION_IDS,
    _COMMAND_RULE_IDS,
    _ENCODING_RULE_IDS,
)

if TYPE_CHECKING:
    from petasos.config.sections import PetasosConfig


def _role(name: str) -> PetasosConfig:
    """The tree for an old profile name. ``code_generation`` is the coding role."""
    role = "coding" if name == "code_generation" else name
    return resolve({"role": role}).config


# The exact tuned configuration this investigation decided (PET-135), widened by
# PET-162 Part 2 to suppress the full injection family on outbound (retained in
# the resolved set under injection_floor_scope="inbound"; the runtime
# direction-aware floor drops them on outbound and keeps them on inbound).
# PET-221: pipe-to-shell stays suppressed. The other four command rules are active.
_EXPECTED_SUPPRESS = (
    _ENCODING_RULE_IDS
    | _ALL_INJECTION_IDS
    | frozenset({"petasos.syntactic.command.pipe-to-shell"})
)

_RETURNED_COMMAND_IDS = _COMMAND_RULE_IDS - frozenset({"petasos.syntactic.command.pipe-to-shell"})

# code_generation demotes the PromptGuard injection verdict (non-floor).
_EXPECTED_SEVERITY_OVERRIDES = {
    "petasos.promptguard.injection": "low",
}

_EXPECTED_CONFIDENCE_FLOOR = 0.6


class TestSuppressionSetIsExactlyDecided:
    """Freeze the adjudicated tuning so any future widening trips review (mirrors
    the frozen-profile invariant in CLAUDE.md), and pin the shipped description."""

    def test_codegen_suppression_set_is_exactly_what_we_decided(self) -> None:
        config = _role("code_generation")
        assert set(config.rules.suppress) == _EXPECTED_SUPPRESS, (
            f"suppress_rules drifted: {sorted(config.rules.suppress)}"
        )
        assert _RETURNED_COMMAND_IDS.isdisjoint(config.rules.suppress)
        for rule_id in sorted(_RETURNED_COMMAND_IDS):
            assert rule_id not in config.rules.suppress
        assert config.rules.confidence_floor == _EXPECTED_CONFIDENCE_FLOOR
        assert dict(config.rules.severity_overrides) == _EXPECTED_SEVERITY_OVERRIDES, (
            f"severity_overrides drifted: {dict(config.rules.severity_overrides)}"
        )
        assert config.rules.injection_floor_scope == "inbound"
        assert config.tools.dangerous_posture == "approve"
