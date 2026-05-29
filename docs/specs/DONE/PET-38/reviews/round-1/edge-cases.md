# Edge-Cases Review -- round 1

## Closure of round N-1 findings
N/A -- round 1

## Findings

### F-1: `_MAX_PARAM_TEXT_BYTES` name vs `len()` character counting
**Severity:** P2
`len(param_text)` counts Unicode code points, not bytes. Constant name and log message imply byte semantics. Rename to `_MAX_PARAM_TEXT_LEN`.

### F-2: `safe_json_dumps` truncation produces invalid JSON
**Severity:** P2
Truncated output is not valid JSON. Functionally harmless since `_scan_params` feeds it to a text scanner, not a JSON parser. Spec should note this.

### F-3: `evaluate()` has no catch-all; `_scan_params` catch-all only covers Step 5
**Severity:** P2
The spec adds a catch-all to `_scan_params` but not `evaluate` itself. Steps 1-4 and 6-8 are unprotected. The spec invokes the "never throws" invariant but should acknowledge this gap in Out of Scope.

### F-4: Test file path discrepancy between spec and brief
**Severity:** P2 (informational)
Brief uses `tests/unit/premium/` (doesn't exist). Spec correctly uses `tests/test_safe_json.py` matching flat convention.

### F-5: Test count discrepancy (13 vs 9)
**Severity:** P2 (informational)
Spec expanded test plan beyond brief's 9 tests. Internally consistent.

### F-6: Module-level constant placement for `_MAX_PARAM_TEXT_BYTES`
**Severity:** P3
Code block implies the constant is declared inside the method body. Should be module-level.

### F-7: No test for empty string values in `tool_params`
**Severity:** P4
`{"a": "", "b": ""}` produces whitespace-only `param_text`. Existing behavior is correct and preserved.

### F-8: `safe_json_dumps(max_depth=0)` edge case
**Severity:** P4
Not reachable since constant is hardcoded at 32 (Decision D4).

### F-9: `_scan_params` catch-all logs via `_logger.exception` which may include sensitive param data
**Severity:** P3
Exception logging may include tool param content in tracebacks. Acceptable for observability but noted.

### F-10: `evaluate()` does not validate `tool_params` type
**Severity:** P3
Non-dict `tool_params` would raise `AttributeError` on `.values()`. Catch-all handles this.

### F-11: Brief requires `mypy --strict .`; spec omits it
**Severity:** P2
Duplicate of correctness F-1.

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 3 | P4: 2

STATUS: GREEN
