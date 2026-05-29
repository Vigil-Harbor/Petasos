# Edge-Cases Review -- round 3

## Closure of round 2 findings

All round 2 findings CLOSED:
- F-1 (P2): Frequency side effect documented in D2 L41 as intentional
- F-2 (P3): test_tier2_allows_exempt_tool reason looseness — acceptable
- F-3 (P3): register() guard bypassed by _load_builtins — correct (private, canonical values)
- F-4 (P3): Test #1 MinimalScanner dependency — correct
- F-5 (P3): No tier2+exempt+malicious test — correct code path, low risk
- F-6 (P4): GUARD-03 assertion — alias defense prevents exempt path

## Findings

### F-1: Empty-vs-non-empty param frequency tracking asymmetry
**Severity:** P3
Empty params short-circuit before `inspect()`, so no frequency update. Non-empty clean params reach `inspect()` with negligible score contribution. Consistent with non-exempt path.

### F-2: No test for exempt tool with None-valued params
**Severity:** P3
`{"key": None}` → parts empty → short-circuit. Existing non-exempt test covers the _scan_params behavior.

### F-3: register() name not normalized (case/whitespace)
**Severity:** P3
Same as round 2 F-3; explicitly deferred in spec. Mixed-case creates dead entry, not a shadow.

### F-4: Concurrent exempt param scans safe under asyncio
**Severity:** P3
Single-threaded event loop prevents dict-level races.

### F-5: Test #4 monkeypatch correctness
**Severity:** P4
`self._pipeline.inspect` resolved at call time, not cached. Monkeypatch works correctly.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 4 | P4: 1

STATUS: GREEN
