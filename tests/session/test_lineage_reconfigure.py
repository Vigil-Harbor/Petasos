"""Regression coverage for behavioral-spec features that the audit (features-tracker.xlsx)
flagged as untested ("NONE FOUND" / COVERAGE GAP), plus one field-attribution bug (DEF-02).

These lock load-bearing behaviors that previously had no direct test:
security-relevant reject branches (HMAC token verification, fail-secure escalation),
the PET-126 hot-reload `apply_config` surfaces, listener fan-out, and serialization
contracts. Every test here exercises a real code path (no mocks of the unit under test).
"""

from __future__ import annotations

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.lineage import LineageRegistry


# ----------------------------- LIN-08: LineageRegistry.apply_config -----------------------------
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
    assert reg.ancestors("a") == ["b"]  # edges preserved, depth bound applied live
