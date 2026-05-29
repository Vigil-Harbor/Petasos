# PET-30 Conventions Review — Round 1

## Findings

### F-1: `__init__.py` package marker breaks adversarial test convention
**Severity:** P2
Existing adversarial test subdirectories have no `__init__.py`. Spec proposes adding one for `tests/adversarial/frequency/`.
**Suggested fix:** Remove `__init__.py` from "New files" table.

### F-2: Brief's `test_guard_derive_tier_checks_tombstone` dropped without acknowledgment
**Severity:** P3
Brief requires a unit test for `_derive_tier()`. Spec replaces with integration tests that subsume coverage but doesn't note the divergence.

### F-3: Config validation follows alerting-era bool guard pattern
**Severity:** P4
More correct pattern, just asymmetric with adjacent fields. Fine as-is.

### F-4: Dead code in `_derive_tier()` — `state.terminated` check unreachable
**Severity:** P3
After `is_terminated()` returns False, `state.terminated` must be False for any live session. The "belt-and-suspenders" check is unreachable dead code.
**Suggested fix:** Remove dead branch, or add comment explaining redundancy.

### F-5: Spec adds PET-34 to `Blocks` header without brief authorization
**Severity:** P3
Reasonable inference from brief body but should be noted as a spec-level addition.

### F-6: Expanded test count (9 to 16) is a silent addition
**Severity:** P3
Good coverage improvement but not flagged as a divergence from brief.

### F-7: `import OrderedDict` placement proposed inside `__init__` method body
**Severity:** P2
Should be module-level import alongside `deque`, matching existing convention.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 4 | P4: 1

STATUS: GREEN
