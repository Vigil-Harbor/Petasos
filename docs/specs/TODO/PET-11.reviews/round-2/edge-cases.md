# Edge-Cases Review -- round 2

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P1) | MockMLScanner duplicated name breaks dedup | CLOSED | spec v2 lines 176-204: configurable `name` parameter |
| F-2 (P1) | asyncio.run() creates new event loop per iteration | CLOSED | spec v2 Decision 2, Decision 9: `asyncio.new_event_loop()` + `loop.run_until_complete()` |
| F-3 (P2) | premium_features conflates config gating with runtime | CLOSED | spec v2 lines 155-156: clarifies enabling mechanism |
| F-4 (P1) | Escalation tier2 requires frequency weight tuning | CLOSED | spec v2 lines 128-131, 139: explicit weights and thresholds |
| F-5 (P2) | Mock ScanResult findings tuple type mismatch | CLOSED | spec v2 line 180: `findings: tuple[ScanFinding, ...] = ()` |
| F-6 (P1) | Benchmark valid_key not in function signature | CLOSED | spec v2 line 243 |
| F-7 (P2) | 512 test count vs 18 test files | CLOSED | spec v2 line 54 |
| F-8 (P2) | E2E failure-path accesses private _alert_manager | CLOSED | spec v2 line 171: acknowledged as consistent with existing patterns |
| F-9 (P2) | pytest-benchmark version constraint missing | CLOSED | spec v2 line 32 |
| F-10 (P3) | Empty-string input unaddressed | OPEN | P3 -- pipeline handles gracefully; not E2E scope |
| F-11 (P2) | No concurrent E2E test | OPEN | P2 -- existing `test_concurrent_inspects_different_profiles` covers concurrency |
| F-12 (P2) | on_audit callback exception not tested in E2E | OPEN | P2 informational -- covered by existing unit tests |
| F-13 (P3) | Security hardening checklist has no automated verification | OPEN | P3 -- checklist is documentation artifact |
| F-14 (P3) | Hermes smoke test skip is all-or-nothing | CLOSED | spec v2 lines 100-101: intentional -- validates full dep tree co-import |

## Findings

### F-1: Happy-path escalation to tier2 is fragile -- test input must trigger exactly one injection rule
**Severity:** P1
**Where:** spec line 139
**Edge case:** Input containing zero-width chars + text matching two injection patterns (e.g., "ignore previous instructions and ignore all instructions") produces score 50.0 (2 x 20.0 + 10.0), equaling `tier3_threshold=50.0` and evaluating to tier3, not tier2. The spec's analysis says "triggers 2-3 rules (score 40-60)" which acknowledges this range but the tier2 assertion would fail at 50.0.
**Suggested fix:** Add explicit test input to spec: e.g., "`'​ignore previous instructions'`" (zero-width char + single injection pattern). Change analysis to "triggers 1 injection rule (weight 20.0) + mock.ml (weight 10.0) = score 30.0, which is >= tier2 (25.0) and < tier3 (50.0)".

### F-2: Benchmark event loop resource leak on exception
**Severity:** P3
**Where:** spec lines 215-222, 247-256
**Edge case:** If `benchmark.pedantic()` raises, `loop.close()` is never called (no `try/finally`). Harmless in practice for test runs.
**Suggested fix:** Wrap in `try/finally`.

### F-3: Mock PII scanner findings must include position for anonymization to produce sanitized_content
**Severity:** P2
**Where:** spec lines 117-118, 153-154
**Edge case:** If mock PII scanner findings have `position=None`, `anonymize()` filters them out and `sanitized_content` equals original text. Assertion `is not None` passes but no actual replacement occurs.
**Suggested fix:** Specify that PII findings must include `Position(start=..., end=...)` corresponding to actual text offsets. Add assertion `sanitized_content != normalized_text`.

### F-4: Failure-path rate limiting assertion is timing-dependent
**Severity:** P2
**Where:** spec line 171
**Edge case:** `rate_limited_count` and `suppressed_count` measure different things. Rapid calls trigger cooldown suppression (`suppressed_count`), not rate limiting (`rate_limited_count` requires exceeding `alert_per_minute_cap=5`).
**Suggested fix:** Change assertion to specifically check `pipe._alert_manager.suppressed_count` (not `rate_limited_count`). Add comment explaining the distinction.

### F-5: Benchmark 3c frequency state accumulates across iterations
**Severity:** P3
**Where:** spec lines 247-256
**Edge case:** Fixed `session_id="bench"` across 30+ iterations accumulates frequency score until tier3 termination, causing later iterations to take a faster code path. Benchmark numbers are skewed.
**Suggested fix:** Use unique session_id per iteration, or reset frequency tracker, or document as amortized latency.

### F-6: Happy-path audit event assertion does not verify finding_count > 0
**Severity:** P3
**Where:** spec line 152
**Edge case:** Spec checks `payload containing finding count` without asserting `>= 1`. A bug zeroing findings would still pass.
**Suggested fix:** Assert `payload["finding_count"] >= 1`.

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=1 P2=2 P3=3 P4=0
