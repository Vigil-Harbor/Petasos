"""Pin live ancestry bounds while preserving registered edges.

See docs/architecture/rationale.md, "Lineage lock order"."""

from __future__ import annotations

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.lineage import LineageRegistry


def test_lineage_apply_config_rebinds_depth_preserves_edges() -> None:
    reg = LineageRegistry(PetasosConfig())
    reg.register("a", "b")
    reg.register("b", "c")
    reg.register("c", "d")
    assert reg.ancestors("a") == ["b", "c", "d"]
    reg.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "tools": {
                    "lineage": {
                        "max_depth": 1,
                    },
                },
            },
        )
    )
    assert reg._max_depth == 1
    assert reg.ancestors("a") == ["b"]
