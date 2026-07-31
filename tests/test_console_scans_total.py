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

PET-165 extends the same pattern to ``_selfmod_total`` /
``get_health()["pipeline"]["selfmod_total"]``, the eviction-proof lifetime count feeding
the console's self-tamper tile. Regression for PET-165: a buffer-scoped tamper count
would silently decay to 0 once 500 ordinary scans evicted the tamper rows, and the
highest-stakes signal is precisely the one that must not decay. The ingest-seam
increment semantics live in ``test_enforcement_events.py``; this module owns the
``/health`` field contract the frontend reads.
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


# ── PET-165: the self-tamper lifetime counter ────────────────────────────────────────


def _selfmod_event(scan_id: str) -> dict[str, object]:
    # Minimal well-formed selfmod_attempt spool row (the shape the reference plugin emits).
    return {
        "event_type": "selfmod_attempt",
        "session_id": "s-selfmod",
        "scan_id": scan_id,
        "tool": "write_file",
        "rule_id": "petasos.selfmod.config_write",
        "severity": "critical",
        "reason": "selfmod target: config.yaml",
    }


async def test_selfmod_total_contract(handlers: ConsoleHandlers) -> None:
    # The /health field the console tile reads: present, an int (not a bool), and an honest
    # zero on a fresh handler. Locks the NAME the frontend depends on.
    health = await handlers.get_health()
    total = health["pipeline"]["selfmod_total"]
    assert type(total) is int  # noqa: E721 -- bool is an int subclass; the field must be a real int
    assert total == 0


async def test_selfmod_total_survives_ring_eviction(handlers: ConsoleHandlers) -> None:
    # The load-bearing regression (PET-165): one self-tamper attempt, then enough ordinary
    # scans to evict it from the 500-entry ring. The row is GONE from the live window but the
    # tile count still reads 1 -- the whole reason the counter is server-side, not derived
    # from the buffer.
    await handlers._surface_enforcement_event(_selfmod_event("e-sm-evict"))
    for i in range(600):
        await handlers.run_scan(f"ordinary scan {i} evicting the tamper row")

    history = await handlers.get_scan_history(limit=1000)
    assert all(e.get("scan_id") != "e-sm-evict" for e in history["entries"]), (
        "precondition: the selfmod row must have been evicted from the live window"
    )

    health = await handlers.get_health()
    assert health["pipeline"]["selfmod_total"] == 1
    assert health["pipeline"]["scans_total"] == 601  # the selfmod row is a recorded scan too


async def test_selfmod_total_counts_unverifiable_rows(handlers: ConsoleHandlers) -> None:
    # Decision 2 pin: unlike the block tally (D4, trusted-claim gated), the selfmod tally is
    # intentionally NOT integrity-gated -- it is detection-only surfacing, never a trusted
    # block claim, and the row renders regardless of provenance. With a spool key configured,
    # an unsigned row verifies as `unverifiable` and must STILL count.
    handlers._spool_key = b"a-console-spool-key"
    await handlers._surface_enforcement_event(_selfmod_event("e-sm-unverified"))

    assert handlers._integrity_recent[-1][0] == "unverifiable"  # precondition
    health = await handlers.get_health()
    assert health["pipeline"]["selfmod_total"] == 1


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
