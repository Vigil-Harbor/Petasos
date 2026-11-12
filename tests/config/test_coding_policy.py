"""Pin coding-role false-positive handling without weakening retained security floors.

See docs/architecture/rationale.md, "Coding-role detector calibration"."""

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


_EXPECTED_SUPPRESS = (
    _ENCODING_RULE_IDS
    | _ALL_INJECTION_IDS
    | frozenset({"petasos.syntactic.command.pipe-to-shell"})
)

_RETURNED_COMMAND_IDS = _COMMAND_RULE_IDS - frozenset({"petasos.syntactic.command.pipe-to-shell"})

_EXPECTED_SEVERITY_OVERRIDES = {
    "petasos.promptguard.injection": "low",
}

_EXPECTED_CONFIDENCE_FLOOR = 0.6


class TestSuppressionSetIsExactlyDecided:
    """Freeze the adjudicated tuning so any future widening trips review (mirrors
    the frozen-profile invariant in CLAUDE.md), and pin the shipped description."""

    def test_codegen_suppression_set_is_exactly_what_we_decided(self) -> None:
        """Pin codegen suppression set is exactly what we decided."""
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
