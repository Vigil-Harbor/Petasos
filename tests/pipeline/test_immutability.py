"""Pin defensive copies and immutable exported state."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.pipeline import Pipeline


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
