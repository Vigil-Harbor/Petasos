# Correctness Review -- round 1

## Closure of round N-1 findings
N/A -- round 1

## Findings

### F-1: Spec drops `mypy --strict .` from Done When criteria
**Severity:** P1
**Where:** spec.md (Done when section)
The brief's Done When explicitly requires `ruff check .` **and** `mypy --strict .` clean. The spec replaces `mypy --strict .` with `ruff format --check .`. While adding `ruff format --check` is good, dropping `mypy --strict` violates a load-bearing brief criterion. CLAUDE.md lists `mypy --strict .` as standard project tooling. The new `_safe_json.py` module introduces `Any` types and a recursive `_walk` function whose return type is `Any` -- exactly the kind of code that benefits from strict mypy checking. The spec's test command also omits mypy.

### F-2: `_MAX_PARAM_TEXT_BYTES` name implies byte measurement but `len()` measures characters
**Severity:** P2
Python's `len()` on a `str` returns code points, not bytes. The constant name `_MAX_PARAM_TEXT_BYTES` suggests byte semantics. Rename to `_MAX_PARAM_TEXT_LEN` or `_MAX_PARAM_TEXT_CHARS`.

### F-3: Brief's stale line numbers not carried into spec
**Severity:** P3 (informational)
The spec correctly uses line numbers from current code. Brief has drifted but spec got it right.

### F-4: Section 2d code block omits type annotations from `_scan_params` signature
**Severity:** P2
The actual signature includes full type annotations. The spec's abbreviated code block could mislead an implementer into stripping them. Add a note that the existing signature is preserved.

### F-5: Truncated `safe_json_dumps` output exceeds `max_size` by 14 chars
**Severity:** P3
`text[:max_size] + "...[truncated]"` produces `max_size + 14` characters. Harmless in practice.

### F-6: Test count wording in Done When
**Severity:** P4
"All 13 tests pass" is internally consistent but should say "All tests in the test command pass" or similar.

## Summary
P0: 0 | P1: 1 | P2: 2 | P3: 2 | P4: 1

STATUS: RED P0=0 P1=1 P2=2 P3=2 P4=1
