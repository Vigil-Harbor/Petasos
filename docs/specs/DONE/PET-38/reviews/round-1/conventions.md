# Conventions Review -- round 1

## Closure of round N-1 findings
N/A -- round 1

## Findings

### F-1: Test #13 placement should clarify "append to existing file"
**Severity:** P2
Spec lists `tests/test_guard.py` in test plan for test #13 without noting it's an existing file with ~500 lines. The "Files to modify" table does say "Add", but the test plan section is ambiguous.

### F-2: `_MAX_PARAM_TEXT_BYTES` should be module-level, not method-level
**Severity:** P2
Every module-level constant in the repo uses leading underscore at module scope: `_SCANNER_TIMEOUT`, `_RATE_LIMIT_WINDOW_SECONDS`, `_NAMESPACE_PREFIX_RE`, `_NONE_SENTINEL`. Constants are never declared inside method bodies.

### F-3: "Done when" omits `mypy --strict .`
**Severity:** P2
CI pipeline runs `mypy --strict .`. Brief requires it. Spec omits it from Done When and test command.

### F-4: Spec line number references are accurate (informational)
**Severity:** P3
The spec's L3, L215-225, L227, L235-240 references are correct against current HEAD.

### F-5: Drawbridge coupling language -- "matching Drawbridge's defaults" framing
**Severity:** P3
CLAUDE.md rejects cross-runtime conformance with Drawbridge. Decision D4 should justify limits on their own merits rather than by appeal to Drawbridge defaults.

### F-6: Module vs inline for N=1 callsite (category (c) addition)
**Severity:** P3
`_safe_json.py` as a separate module is justified by D1 for future reuse. N=1 callsite today. Flagged for drift-check awareness per protocol.

### F-7: Test count mismatch with brief (category (c) -- positive expansion)
**Severity:** P3
Spec adds 4 tests beyond brief's 9. More coverage is good.

### F-8: `_MAX_PARAM_TEXT_BYTES` naming vs character semantics
**Severity:** P4
Rename to `_MAX_PARAM_TEXT_LEN` for accuracy.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 4 | P4: 1

STATUS: GREEN
