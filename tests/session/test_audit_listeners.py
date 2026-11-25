"""Pin audit listener delivery without leaking callback failures.

See docs/architecture/rationale.md, "Alert and audit test constraints"."""

from __future__ import annotations

from petasos.config.schema import from_mapping
from petasos.config.sections import PetasosConfig
from petasos.model import PipelineResult
from petasos.session.audit import AuditEmitter


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
    assert len(seen) == 1
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
    assert "scanner_results" in ev2.payload
    assert em._global_sequence == 2
