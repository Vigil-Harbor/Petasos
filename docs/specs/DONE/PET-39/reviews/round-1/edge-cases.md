# Edge-Cases Review -- round 1

## Findings

### F-1: Pinned fingerprint is platform-dependent due to CRLF/LF divergence
**Severity:** P0
**Where:** spec.md:42, spec.md:98
Same as correctness F-1. On Windows `public.pem` is 116 bytes (CRLF), on Linux 114 bytes (LF). The pinned hash is the Windows variant.

### F-2: `clock_skew_seconds=float('nan')` bypasses both guard checks
**Severity:** P1
**Where:** spec.md:80-85 (Design section 1)
NaN passes both `nan < 0` (False) and `nan > 300` (False) due to IEEE 754. `timedelta(seconds=float('nan'))` then raises ValueError with a confusing internal error.
**Suggested fix:** Use `math.isfinite()` or `not (0 <= x <= 300)` pattern.

### F-3: Claims except clause does not catch TypeError from malformed features
**Severity:** P1
**Where:** spec.md:142-151 (Design section 4)
A signed JWT with `features: 42` (integer) passes decode. `frozenset(42)` raises `TypeError`, not caught by `except (OverflowError, OSError, ValueError)`.
**Suggested fix:** Add `TypeError` to except clause.

### F-4: `valid_tiers=frozenset()` silently rejects all tokens
**Severity:** P2
**Where:** spec.md:87
Empty frozenset is not `None`, so it's used as-is. Every tier check fails.
**Suggested fix:** Add guard: `if valid_tiers is not None and len(valid_tiers) == 0: raise ValueError(...)`.

### F-5: No test for `tier=""` (empty string)
**Severity:** P2
**Where:** spec.md:159-178
Empty string correctly rejected but no regression test covers it.

### F-6: No test for missing tier claim (distinct from tier=None)
**Severity:** P2
**Where:** spec.md:159-178
Same as correctness F-3.

### F-7: Test #5 has ambiguous assertion
**Severity:** P3
**Where:** spec.md:168
Test accepts both INVALID and VALID — not a useful regression gate.
**Suggested fix:** Either use a deterministically-overflowing value or rename as a "no raise" contract test.

### F-8: `_DEFAULT_VALIDATOR` singleton doesn't expose valid_tiers
**Severity:** P3
**Where:** spec.md, license.py:77-85
Convenience function can't customize tiers. Acceptable for now, should be noted in scope.

### F-9: Thread-safety of singleton initialization
**Severity:** P3
Pre-existing condition. Benign race. No action needed for this spec.

## Summary
P0: 1 | P1: 2 | P2: 3 | P3: 3 | P4: 0

STATUS: RED P0=1 P1=2 P2=3 P3=3 P4=0
