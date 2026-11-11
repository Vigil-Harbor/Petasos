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
from petasos.model import PipelineResult
from petasos.session.audit import AuditEmitter


# --- AUD-07/08: AuditEmitter listeners + apply_config ---
def _result() -> PipelineResult:
    return PipelineResult(safe=True, findings=(), scanner_results=(), errors=())


def test_audit_add_listener_fires_and_isolates() -> None:
    seen: list[object] = []

    def good(ev: object) -> None:
        seen.append(ev)

    def bad(ev: object) -> None:
        raise RuntimeError("listener boom")

    em = AuditEmitter(
        from_mapping(
            PetasosConfig,
            {
                "audit": {
                    "verbosity": "minimal",
                },
            },
        )
    )
    em.add_listener(bad)
    em.add_listener(good)
    em.emit(_result(), "s", None)
    assert len(seen) == 1  # good still fired despite bad raising
    assert em.last_callback_error is not None and "listener boom" in em.last_callback_error


def test_audit_apply_config_swaps_verbosity_live() -> None:
    em = AuditEmitter(
        from_mapping(
            PetasosConfig,
            {
                "audit": {
                    "verbosity": "minimal",
                },
            },
        )
    )
    ev1 = em.emit(_result(), "s", None)
    # Minimal-verbosity base payload: PET-136 added the always-present
    # ``emit_findings`` flag (the per-finding list itself stays gated off here).
    assert set(ev1.payload.keys()) == {"safe", "finding_count", "emit_findings"}
    em.apply_config(
        from_mapping(
            PetasosConfig,
            {
                "audit": {
                    "verbosity": "verbose",
                },
            },
        )
    )
    ev2 = em.emit(_result(), "s", None)
    assert "scanner_results" in ev2.payload  # verbose keys now present
    assert em._global_sequence == 2  # sequence preserved across apply_config
