# Edge-Cases Review — round 2

## Closure of round 1 findings
Round-1 P0/P1 items CLOSED or DEFERRED as in the author's closure_manifest. Deferred rows D-1–D-5 well-formed.

## Findings

### F-1: Plugin wiring sketch omits `inspect_lock`, so the ingest head inspect can race evaluate
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:215–221 (§ Plugin wiring); spec.md:193, 202 (§ Helper contract step 3)
**Suggested fix:** Pin `_ingest_one` to `await scan_ingestion_result(..., inspect_lock=_inspect_lock, session_id=session_id if armed else None, weight_cap=guard.scan_weight_cap if armed else 0.0)`. Isolation / reconfigure-yield tests already assume the mutex is on that call.

### F-2: Flagged (findings-path) banner is not pinned to state the coverage regime
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:239 (§ Banner); spec.md:223 (§ Plugin wiring); spec.md:332 (§ Done when)
**Suggested fix:** On the findings path, call `format_result_notice(..., scanned_chars=scan.coverage.scanned_chars, total_chars=scan.coverage.total_chars, coverage=scan.coverage.regime)`. Add a handler test: flagged 100k result banner contains `Coverage: full.`; flagged 1_000_001-char result contains `Coverage: ceiling.` and `Scanned 1000000 of 1000001`.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 0 | P4: 0

STATUS: GREEN
