# Conventions Review -- round 3

## Closure of round 2 findings

All round 2 findings CLOSED:
- F-1 (P1): Missing test_premium_integration.py → spec L22 adds to Files changed, L176-189 adds test update, L427 includes in test command
- F-2 (P3): Drawbridge audit divergence — Petasos is uncoupled per CLAUDE.md
- F-3–F-5 (P3): Silent Done-when additions — all category (c), well-motivated

## Findings

### F-1: PROF-03 tests placed in test_suppress_bypass.py (naming stretch)
**Severity:** P3
PROF-03 tests (built-in name overwrite) placed in a file named "suppress_bypass" which focuses on PET-59/PROF-04 rule suppression. Consider `test_builtin_overwrite.py` or acknowledge the naming stretch.

### F-2: D1 remaps config.exempt_param_scan to constructor — category (c)
**Severity:** P3
Well-documented departure from brief. Carried from rounds 1-2.

### F-3: frozenset conversion aligns with frozen exports convention
**Severity:** P4
Positive alignment with CLAUDE.md.

### F-4: Brief audit Done-when reinterpreted as consumer-side logging
**Severity:** P3
Category (c) addition. Drawbridge decision scoped to DBR, not PET. Rationale sound.

### F-5: Test #4 mock type annotation matches existing patterns
**Severity:** P4
Matches PET-38 test conventions.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 2

STATUS: GREEN
