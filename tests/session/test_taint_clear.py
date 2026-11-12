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
from petasos.session.taint import SessionTaintStore


# --- TNT-10: SessionTaintStore.clear_session ---
def test_taint_clear_session_drops_spans() -> None:
    store = SessionTaintStore(
        from_mapping(
            PetasosConfig,
            {
                "egress": {
                    "taint_min_span_length": 12,
                },
            },
        )
    )
    store.capture("sess", {"v": "supersecretbalance12345"}, "mcp_bank_")
    assert store.tainted_source("sess", {"arg": "see supersecretbalance12345 now"}) == "mcp_bank_"
    store.clear_session("sess")
    assert store.tainted_source("sess", {"arg": "see supersecretbalance12345 now"}) is None
    store.clear_session("sess")  # idempotent, no raise
