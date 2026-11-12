"""Pin live lineage depth and expiry bounds without losing edges.

See docs/architecture/rationale.md, "Lineage lock order"."""

from __future__ import annotations

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.lineage import LineageRegistry


def test_lineage_registry_apply_config_updates_bounds() -> None:
    reg = LineageRegistry(
        from_mapping(
            PetasosConfig,
            {
                "tools": {
                    "lineage": {
                        "max_depth": 2,
                    },
                },
            },
        )
    )
    reg.register("a", "b")
    reg.register("b", "c")
    reg.register("c", "d")
    assert reg.ancestors("a") == ["b", "c"]

    reg.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "tools": {
                    "lineage": {
                        "max_depth": 8,
                    },
                },
            },
        )
    )

    assert reg._max_depth == 8
    assert reg.ancestors("a") == ["b", "c", "d"]
    assert reg._edges
