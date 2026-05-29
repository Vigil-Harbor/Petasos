# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Catching `KeyboardInterrupt` and `SystemExit` violates Python runtime expectations
**Severity:** P1
A user pressing Ctrl+C during a scan will not interrupt the process -- the pipeline swallows the interrupt. Similarly `sys.exit()` is caught. The brief's D1/D2 say `BaseException` but don't distinguish CancelledError (the actual vulnerability) from KI/SE (process signals that should propagate).
**Suggested fix:** Re-raise KI/SE after logging, or catch `(Exception, asyncio.CancelledError)` instead.

### F-2: D2 rationale misleading -- external cancellation cancels ALL scanners
**Severity:** P1
D2 says "a cancelled scanner returns an errored ScanResult, and the remaining scanners continue." For external `task.cancel()`, ALL scanners receive CancelledError simultaneously. The rationale creates a false mental model.
**Suggested fix:** Amend D2 to state that under external cancellation, all scanners are cancelled together.

### F-3: Test 6 race condition
**Severity:** P2
`asyncio.sleep` + `task.cancel()` is non-deterministic. Use event-based cancellation.

### F-4: `_normalize_gather_result` empty error string for bare CancelledError
**Severity:** P2
`f"{type(result).__name__}: {result}"` produces `"CancelledError: "` with trailing colon.

### F-5: D4 false for external cancellation during post-gather stages
**Severity:** P2
External `task.cancel()` can arrive at any `await` in stages 6/7/10/11. D4's reasoning is wrong even though the outcome is acceptable (outer handler catches it).

### F-8: `asyncio.wait_for` internal cancellation mechanics on Python 3.12+
**Severity:** P2
Note that the `except BaseException` in `_scan_one` is outside `wait_for` and does not interfere with its internal cancel/uncancel protocol.

### F-7: No test for `_normalize_gather_result` identity path
**Severity:** P3

### F-9: Test 5 log lacks actionable context (session_id)
**Severity:** P3

### F-10: No test for cancellation with zero ML scanners
**Severity:** P3

## Summary
P0: 0 | P1: 2 | P2: 4 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=2 P2=4 P3=3 P4=0
