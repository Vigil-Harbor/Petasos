"""Pin explicit removal of retained source-taint state.

See docs/architecture/rationale.md, "Source taint bounds"."""

from __future__ import annotations

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.session.taint import SessionTaintStore


def test_taint_clear_session_drops_spans() -> None:
    """Pin taint clear session drops spans."""
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
    store.clear_session("sess")
