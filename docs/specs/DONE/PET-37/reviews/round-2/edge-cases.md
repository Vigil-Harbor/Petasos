# Edge-Cases Review -- round 2

## Closure of round 1 findings

All round 1 findings CLOSED:
- F-1 (P1): Spec lines 29-30 and Done-when L421 corrected — AuditEmitter consumes PipelineResult, not GuardResult
- F-2 (P4): Mock pattern matches existing conventions
- F-3 (P2): Case-insensitive bypass explicitly deferred (L431)
- F-4–F-8 (P3/P4): All acknowledged or addressed

## Findings

### F-1: Exempt tool param scan frequency side effect undocumented
**Severity:** P2
`_scan_params()` calls `pipeline.inspect()` which updates frequency tracking. An exempt tool's params contribute to session escalation. This is arguably correct but undocumented.
**Suggested fix:** Add a note to D2 acknowledging the frequency side effect as intentional.

### F-2: test_tier2_allows_exempt_tool reason string looseness
**Severity:** P3
Test asserts `"exempt" in result.reason` which matches both old and new strings. Less diagnostic but correct.

### F-3: register() guard bypassed by _load_builtins direct write
**Severity:** P3
`_load_builtins` writes to `self._profiles` directly, bypassing `register()`. Correct behavior since it writes canonical values.

### F-4: Test #1 depends on MinimalScanner detecting injection in params
**Severity:** P3
Works correctly — MinimalScanner runs regardless of premium status.

### F-5: No test for tier2 + exempt + malicious params combination
**Severity:** P3
Interesting operational case untested but code path is correct.

### F-6: GUARD-03 test assertion could exclude "exempt-with-scan"
**Severity:** P4
Test still passes — alias defense prevents exempt path. Forward-looking robustness nit.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 4 | P4: 1

STATUS: GREEN
