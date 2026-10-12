# Correctness Review — round 2

## Closure of round 1 findings
| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Ceiling-clean banner uses the findings path and claims injection was found | CLOSED | spec § Banner: ceiling-clean calls `path="ceiling"`, never `path="findings"` |
| correctness | F-2 | Helper never-throws leaves inspect failures as silent pass-through | DEFERRED | well-formed `D-2` |
| correctness | F-3 | Production ingest path moves off `_run_async`; test doubles do not | DEFERRED | well-formed `D-3` |
| correctness | F-4 | Reconfigure lock acquire is cancel-unsafe against `_maybe_reconfigure`'s 15s `_run_async` | DEFERRED | well-formed `D-1` |
| edge-cases | F-1 | `to_thread(Lock.acquire)` plus `_run_async` cancel leaks `_inspect_lock` | DEFERRED | well-formed `D-1` |
| edge-cases | F-2 | cancelled `inspect()` is swallowed; the helper sweep then runs with no deadline | DEFERRED | well-formed `D-4` |
| edge-cases | F-3 | chunk / floor errors still report `coverage=full` with a silent gap | DEFERRED | well-formed `D-5` |
| edge-cases | F-4 | ceiling-clean banner reuses the "injection found" findings boilerplate | CLOSED | same fold as correctness F-1 |

## Findings

### F-1: Decision 11 timeout-after-lock contradicts Plugin wiring's `_run_async` twin
**Severity:** P0
**Where:** spec.md:110 | spec § Decision 11; spec.md:214-221 | spec § Plugin wiring
**Claim:** Decision 11: “The outer `_run_ingest_async` timeout starts **after** the ingest lock is acquired, not at submit." Plugin wiring then says `_run_ingest_async` is `_run_async`'s twin with `timeout=budget` at submit.
**Why this is wrong:** `_run_async` starts its clock at submit. A twin wrapping `_ingest_one` therefore times the lock wait plus the scan. That is the shape Decision 11 names and rejects.
**Suggested fix:** Pick one implementable shape and make both sections say it. The Decision 11 shape is two-phase on the Hermes thread, for example: `_ingest_one` acquires the `asyncio.Lock`, then applies `timeout=budget` (via `asyncio.wait_for` or by notifying `_run_ingest_async` that the lock is held); `_run_ingest_async` waits unbounded until that signal, then `future.result(timeout=budget)` / cancel-and-re-raise. Delete `timeout=budget` on the submit that still includes the lock, or document it as a failsafe that is *not* `_result_scan_timeout()` and is not the Decision 11 clock. Do not call `_run_ingest_async` “`_run_async`'s twin” unless the timer-at-submit behavior is also adopted and Decision 11 is reverted.

### F-2: Flagged-above-ceiling `format_result_notice` call does not pin `scanned_chars` from coverage
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:158 | spec § Coverage regimes; spec.md:238-240 | spec § Banner; spec.md:223 | spec § Plugin wiring
**Suggested fix:** Pin the findings-path call: `path="findings"`, `scanned_chars=scan.coverage.scanned_chars`, `total_chars=scan.coverage.total_chars`, `coverage=scan.coverage.regime`. Same numbers in the `ingest_flagged` reason’s `scanned=` / `len=` / `coverage=`. Extend `format_result_notice`’s scanned-line gate from `path == "findings"` to also fire on `path == "ceiling"` (already stated for the clean path).

## Summary
P0: 1 | P1: 0 | P2: 1 | P3: 0 | P4: 0

STATUS: RED P0=1 P1=0 P2=1 P3=0 P4=0
