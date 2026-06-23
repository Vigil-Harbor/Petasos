"""PET-144: eviction-proof lifetime scan count surfaced in get_health.

The console scan history is a fixed 500-entry ring (RingBuffer(maxlen=500)). Past
entry 500 the oldest row drops, and before PET-144 nothing surfaced a total count, so
an operator saw a <=500 window presented as the whole record. ConsoleHandlers now keeps
``_scans_total`` -- a monotonic, in-memory counter decoupled from the ring (mirrors the
PET-131 ``_block_tally`` / PET-138 ``_bypass_tally`` eviction-proof pattern) -- bumped
through one private ``_record_scan`` chokepoint that BOTH push sites (the playground
``run_scan`` and the drained-enforcement fold) route through, and exposes it as
``get_health()["pipeline"]["scans_total"]``.

Regression for PET-144: the count must stay accurate after the ring has evicted, both
record paths must feed the same counter, and the first overflow must log exactly once
(not per scan). The 500 ring stays a hard cap by design -- this makes it honest, not
bigger.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("fastapi")

from petasos.config import PetasosConfig  # noqa: E402
from petasos.console.server import ConsoleHandlers  # noqa: E402
from petasos.pipeline import Pipeline  # noqa: E402
from petasos.scanners.minimal import MinimalScanner  # noqa: E402


@pytest.fixture()
def handlers() -> ConsoleHandlers:
    return ConsoleHandlers(
        Pipeline(scanners=[MinimalScanner()], config=PetasosConfig(fail_mode="degraded"))
    )


async def test_scans_total_starts_zero(handlers: ConsoleHandlers) -> None:
    # Honest zero: a fresh handler reports scans_total == 0 before any scan -- the
    # baseline the eviction-proof claim builds on.
    health = await handlers.get_health()
    assert health["pipeline"]["scans_total"] == 0


async def test_scans_total_survives_ring_eviction(handlers: ConsoleHandlers) -> None:
    # The count is accurate even though retention is capped (mirrors the eviction-proof
    # assertion in test_disarm_bypass_counter.py): 600 recorded, 500 retained, total 600.
    for i in range(600):
        await handlers.run_scan(f"scan number {i} for ring eviction coverage")

    # get_health does NOT drain, so the counter reflects exactly the 600 run_scan records.
    health = await handlers.get_health()
    assert health["pipeline"]["scans_total"] == 600

    # The ring itself stays hard-capped at 500 (bounded-memory by design)...
    assert len(handlers.scan_history) == 500
    # ...and the public history surface returns at most that window, even asking for 1000.
    history = await handlers.get_scan_history(limit=1000)
    assert len(history["entries"]) == 500


async def test_scans_total_counts_both_record_paths(handlers: ConsoleHandlers) -> None:
    # Both chokepoint callers bump the same counter: one playground run_scan (+1) and one
    # drained-enforcement fold (+1). Structurally guaranteed by the single _record_scan
    # method; pinned here so the two paths can never diverge. The fold uses a minimal
    # well-formed row; its await self.sse.broadcast(...) is a no-op (no subscribers on a
    # fresh handler). We assert only the counter, not row contents.
    await handlers.run_scan("one playground scan")
    await handlers._surface_enforcement_event(
        {"event_type": "block", "session_id": "s1", "scan_id": "e-1"}
    )

    health = await handlers.get_health()
    assert health["pipeline"]["scans_total"] == 2


async def test_ring_overflow_warns_once(
    handlers: ConsoleHandlers, caplog: pytest.LogCaptureFixture
) -> None:
    # The first ring overflow logs exactly one WARNING (no per-scan log spam). Filter by
    # the "ring at capacity" substring rather than len(caplog.records): the same
    # petasos.console.server logger also emits the enforcement-spool over-cap WARNING and
    # the .rot unlink-failure WARNING; the pure run_scan path never triggers those, but
    # the substring filter keeps the test robust if it later drains enforcement.
    with caplog.at_level(logging.WARNING, logger="petasos.console.server"):
        for i in range(600):
            await handlers.run_scan(f"overflow scan {i}")

    overflow_warnings = [r for r in caplog.records if "ring at capacity" in r.message]
    assert len(overflow_warnings) == 1
