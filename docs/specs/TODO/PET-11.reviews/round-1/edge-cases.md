# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: MockMLScanner duplicated `name` property breaks multi-scanner dedup and audit tracing
**Severity:** P1
**Where:** spec.md:142-155 (Mock Scanner Implementation)
**Suggested fix:** Make the `name` property configurable with distinct names for the two-scanner failure test.

### F-2: `asyncio.run()` wrapping inside `benchmark.pedantic()` creates a new event loop per iteration
**Severity:** P1
**Where:** spec.md:166-171 (3a. Syntactic-only benchmark)
**Suggested fix:** Use `loop.run_until_complete()` with a pre-created event loop, or document that the measured time includes event-loop overhead.

### F-3: Spec asserts `result.premium_features` shows all "available" but conflates config gating with runtime execution
**Severity:** P2
**Where:** spec.md:122 (Happy Path step 9)
**Suggested fix:** Clarify that `premium_features` verifies license+config gating, not runtime execution.

### F-4: E2E happy-path escalation assertion "tier2" requires specific frequency weight tuning not specified in the setup
**Severity:** P1
**Where:** spec.md:119 (Happy Path step 5)
**Suggested fix:** Specify explicit config overrides for weights and thresholds.

### F-5: Mock scanner `ScanResult` uses `findings` as a tuple but mock passes it as a constructor arg -- type mismatch risk
**Severity:** P2
**Where:** spec.md:154

### F-6: Benchmark test `test_benchmark_full_pipeline` calls `pipe.activate(valid_key)` but `valid_key` is not in function signature
**Severity:** P1
**Where:** spec.md:193-200
**Suggested fix:** Update function signature to include `valid_key`.

### F-7: 512 test count vs 18 test files (not 20)
**Severity:** P2
**Where:** spec.md:52

### F-8: E2E failure-path accesses private `_alert_manager` attribute
**Severity:** P2
**Where:** spec.md:137
**Suggested fix:** Note the private access follows existing test conventions.

### F-9: `pytest-benchmark` version constraint missing
**Severity:** P2
**Where:** spec.md:30
**Suggested fix:** Specify `"pytest-benchmark>=4.0,<5"`.

### F-10: Empty-string input to `Pipeline.inspect()` is unaddressed
**Severity:** P3

### F-11: No concurrent E2E test despite shared mutable state
**Severity:** P2

### F-12: `on_audit` callback exception not tested in E2E happy path
**Severity:** P2
Informational — already covered by existing unit tests.

### F-13: Security hardening checklist has no automated verification
**Severity:** P3

### F-14: Hermes smoke test skip is all-or-nothing for spacy + transformers
**Severity:** P3

## Summary
P0: 0 | P1: 3 | P2: 5 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=3 P2=5 P3=3 P4=0
