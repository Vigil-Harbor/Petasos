# Scalability Review — round 2

## Closure of round 1 findings
scalability/R1/F-1 CLOSED (CHANGELOG residuals). scalability/R1/F-2 PARTIAL — Decision 11 pins after-lock start; Plugin wiring still submits as `_run_async`'s twin.

Deferred rows D-1–D-5 well-formed.

## Findings

### F-1: Plugin wiring still starts the ingest timeout at submit, undoing Decision 11's after-lock pin
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec § Decision 11; spec § Plugin wiring (`_run_ingest_async(..., timeout=budget)` + “twin” of `_run_async`)
**Suggested fix:** Make the two sections name one protocol. `_run_ingest_async` waits on `future.result()` with no scan-budget timeout (caller patience / host join). Inside `_ingest_one`, after the K=1 `asyncio.Lock` is held, `await asyncio.wait_for(scan_ingestion_result(...), timeout=budget)` (or equivalent). Drop `timeout=budget` from the `_run_ingest_async` call, or document that argument as unused. Keep cancel-and-re-raise on the wait_for expiry. The 8-wide helper benchmark still records serialization and does not assert every slot finishes inside the scan budget.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 0

STATUS: GREEN
