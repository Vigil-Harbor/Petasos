from __future__ import annotations

from types import MappingProxyType

import pytest

from petasos.config.layers import ROLES
from petasos.config.schema import from_mapping, to_mapping
from petasos.config.sections import PetasosConfig
from petasos.pipeline import Pipeline
from petasos.scanners.minimal.taxonomy import RULE_TAXONOMY


class TestDefensiveCopies:
    def test_pipeline_config_is_copy(self) -> None:
        cfg = PetasosConfig()
        p = Pipeline(config=cfg)
        assert p.config == cfg
        with pytest.raises(AttributeError):
            p.config.fail_mode = "open"  # type: ignore[misc]

    def test_feature_status_is_mapping_proxy(self) -> None:
        p = Pipeline(
            config=from_mapping(
                PetasosConfig,
                {
                    "frequency": {
                        "enabled": True,
                    },
                },
            )
        )
        result_sync = p._build_feature_status()
        assert isinstance(result_sync, MappingProxyType)
        with pytest.raises(TypeError):
            result_sync["frequency"] = "hacked"  # type: ignore[index]


class TestImmutableExports:
    def test_rule_taxonomy_is_frozenset(self) -> None:
        assert isinstance(RULE_TAXONOMY, frozenset)

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
