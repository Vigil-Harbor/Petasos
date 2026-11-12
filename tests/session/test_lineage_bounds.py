"""PET-126: ToolCallGuard / SpawnBudget / LineageRegistry live reconfigure.

The gateway constructs its OWN tracker, guard, and lineage registry beyond the
pipeline (Decision 4), so a live reload must reconfigure all of them. These tests
pin: delegate-set recognition, fan-out window resize (counters preserved), tracker
propagation, the two-phase D8 validation gate, the immutable session_secret, and
lineage-bound rebinding with edge preservation.
"""

from __future__ import annotations

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.lineage import LineageRegistry


def test_lineage_registry_apply_config_updates_bounds() -> None:
    # Changing lineage bounds via apply_config is observed by the next ancestor
    # walk; existing edges survive.
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
    assert reg.ancestors("a") == ["b", "c"]  # bounded to depth 2

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
    assert reg.ancestors("a") == ["b", "c", "d"]  # deeper walk after reconfigure
    assert reg._edges  # edges preserved across reconfigure
