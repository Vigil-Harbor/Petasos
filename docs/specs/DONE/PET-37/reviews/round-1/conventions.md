# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: D1 remaps exempt_param_scan from config to constructor — authorized with rationale (category c)
**Severity:** P3
Brief says `config.exempt_param_scan`; spec remaps to constructor with explicit rationale (Brief 3 parallelism contract). Category (c) addition, well-documented.

### F-2: keyword-only separator is new pattern but safe
**Severity:** P2
Current constructor has no `*` separator; spec adds one before `exempt_param_scan`. All existing callsites pass `profile` by keyword. No breakage.

### F-3: _BUILTIN_NAMES consumer claim incomplete
**Severity:** P4
Spec says "the only consumer that iterates" is `_load_builtins`, but `tests/test_profiles.py` and `tests/test_profiles_suppress.py` also iterate. All are order-independent — no functional impact.

### F-4: D2 reason="exempt-with-scan" authorized by brief
**Severity:** P3 (withdrawn)
Brief explicitly authorizes this reason string.

### F-5: D4 hard reject authorized by brief
**Severity:** P3 (withdrawn)
Brief explicitly authorizes ValueError.

### F-6: Spec adds exempt_param_scan=False as Done-when not in brief
**Severity:** P3
Category (c) addition — elevates implicit brief decision into acceptance criterion. Well-motivated.

### F-7: Test #4 mock works through catch-all indirection
**Severity:** P2
Works correctly; matches existing test patterns in test_guard.py.

### F-8: _BUILTIN_NAMES has 3 iteration consumers, not 1
**Severity:** P4
Same as F-3 — spec claim imprecise but impact analysis correct.

### F-9: frozenset conversion aligns with CLAUDE.md frozen exports invariant
**Severity:** P3 (positive alignment)

### F-10: New tests inline construction instead of reusing helper
**Severity:** P4
New tests need monkeypatch for premium active; existing helper doesn't support it. Inlining is correct.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 4

STATUS: GREEN
