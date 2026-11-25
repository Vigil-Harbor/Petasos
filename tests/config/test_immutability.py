"""Pin defensive copies and immutable exported state."""

from __future__ import annotations

from types import MappingProxyType

from petasos.config.layers import ROLES
from petasos.config.schema import from_mapping, to_mapping
from petasos.config.sections import PetasosConfig


class TestImmutableExports:
    def test_builtin_profiles_immutable(self) -> None:
        for role in ROLES.values():
            assert isinstance(role.document, MappingProxyType)

    def test_config_copy_preserves_frequency_weights(self) -> None:
        cfg = from_mapping(
            PetasosConfig,
            {
                "frequency": {
                    "weights": {"injection": 10.0},
                },
            },
        )
        copy = from_mapping(PetasosConfig, to_mapping(cfg))
        assert isinstance(cfg.frequency.weights, MappingProxyType)
        assert isinstance(copy.frequency.weights, MappingProxyType)
        assert copy.frequency.weights == cfg.frequency.weights
        assert copy.frequency.weights is not cfg.frequency.weights
