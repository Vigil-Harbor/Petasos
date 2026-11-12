"""Pin inbound injection floors and direction-independent structural floors.

See docs/architecture/rationale.md, "Finding suppression floors"."""

from __future__ import annotations

import pytest

from petasos.config.layers import resolve
from petasos.config.schema import ConfigError, evolve, from_mapping
from petasos.config.sections import PetasosConfig
from petasos.scanners.minimal.taxonomy import (
    _ALL_INJECTION_IDS,
)


class TestRoleFloorScope:
    """The coding role keeps the injection floor on inbound text only."""

    def test_codegen_suppresses_the_full_injection_family(self) -> None:
        suppress = set(resolve({"role": "coding"}).config.rules.suppress)
        assert {rule for rule in suppress if rule in _ALL_INJECTION_IDS} == _ALL_INJECTION_IDS

    def test_other_roles_keep_the_floor_on_every_direction(self) -> None:
        for name in ("general", "support", "research", "admin"):
            scope = resolve({"role": name}).config.rules.injection_floor_scope
            assert scope == "all", name
        assert resolve({"role": "coding"}).config.rules.injection_floor_scope == "inbound"

    def test_inbound_scope_can_name_the_injection_family(self) -> None:
        config = from_mapping(
            PetasosConfig,
            {
                "rules": {
                    "injection_floor_scope": "inbound",
                    "suppress": sorted(_ALL_INJECTION_IDS),
                }
            },
        )
        assert set(config.rules.suppress) >= _ALL_INJECTION_IDS

    @pytest.mark.parametrize("bad", ["outbound", "", "All", "Inbound"])
    def test_invalid_scope_is_refused(self, bad: str) -> None:
        with pytest.raises(ConfigError, match="rules.injection_floor_scope"):
            from_mapping(PetasosConfig, {"rules": {"injection_floor_scope": bad}})


class TestDangerousToolPosture:
    """General and coding ask. Research, support and admin block. A typo is refused."""

    def test_default_posture_is_block(self) -> None:
        assert PetasosConfig().tools.dangerous_posture == "block"

    def test_builtins(self) -> None:
        for name in ("general", "coding"):
            posture = resolve({"role": name}).config.tools.dangerous_posture
            assert posture == "approve", name
        for name in ("admin", "support", "research"):
            posture = resolve({"role": name}).config.tools.dangerous_posture
            assert posture == "block", name

    def test_unknown_value_is_refused(self) -> None:
        with pytest.raises(ConfigError, match="tools.dangerous_posture"):
            from_mapping(PetasosConfig, {"tools": {"dangerous_posture": "Approve"}})

    def test_a_rule_change_keeps_the_coding_posture(self) -> None:
        merged = evolve(
            resolve({"role": "coding"}).config,
            {"rules": {"confidence_floor": 0.5}},
        )
        assert merged.tools.dangerous_posture == "approve"
