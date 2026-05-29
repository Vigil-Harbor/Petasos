# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: `_scan_one` error format produces empty string for `CancelledError`, breaking test assertions
**Severity:** P1
**Where:** spec.md Design section 2 (line 69-82) and Test plan tests 1, 2
**Claim:** The spec leaves `_scan_one`'s error body unchanged: `error=str(exc)`. Tests 1 and 2 assert the error string "mentions 'CancelledError'".
**Why this is wrong:** `str(asyncio.CancelledError())` returns `""` (empty string) in Python 3.11+. The existing `_scan_one` handler uses `error=str(exc)` (pipeline.py L147), which would produce `error=""` for a CancelledError. Test 2 asserts `ScanResult.error` contains "CancelledError" -- but `str(CancelledError())` is `""`. Also inconsistent with `_normalize_gather_result` which uses `f"{type(result).__name__}: {result}"`.
**Suggested fix:** Change `_scan_one`'s error format to `error=f"{type(exc).__name__}: {exc}"`. Unifies the format and ensures non-empty error strings.

### F-2: Test 5 expects `_logger.warning` to fire for a scanner-raised `CancelledError`, but D2 catches it first
**Severity:** P1
**Where:** Test plan test 5 vs. Design section 2 and Design section 5
**Claim:** Test 5: "Patch `_logger.warning`, trigger `CancelledError` through a scanner."
**Why this is wrong:** A scanner that raises `CancelledError` in `scan()` is caught by `_scan_one`'s `except BaseException` handler (D2). It returns an errored `ScanResult` and never propagates to `inspect()`. The `_logger.warning` at the `inspect()` boundary only fires for exceptions that reach the outer handler. The test would fail.
**Suggested fix:** Change test 5 to inject `CancelledError` at the `inspect()` level (e.g., patch `_inspect_inner` to raise `CancelledError`).

### F-3: D6 incorrectly cites `petasos/premium/audit.py` as using `import logging`
**Severity:** P2
`audit.py` does NOT use logging. Correct examples: `alerting.py`, `guard.py`, `profiles/__init__.py`.

### F-4: Import placement instruction could trigger ruff I001
**Severity:** P2
"After the existing imports (before `_SEVERITY_RANK`)" is ambiguous. Should specify stdlib import block.

### F-5: Brief's done-when for `pytest --cov` deferred to Out of Scope
**Severity:** P2
The brief explicitly lists this as a done-when criterion. Spec should either adopt it or note the deviation as a decision.

### F-6: Inconsistent error format between `_scan_one` and `_normalize_gather_result`
**Severity:** P3
Both are error paths for scanner exceptions. Different string formats.

## Summary
P0: 0 | P1: 2 | P2: 3 | P3: 1 | P4: 0

STATUS: RED P0=0 P1=2 P2=3 P3=1 P4=0
