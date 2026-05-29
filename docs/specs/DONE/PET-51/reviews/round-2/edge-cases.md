# Edge-Cases Review -- round 2

## Closure of round 1 findings

All round 1 P1 findings CLOSED:
- F-1 (transitive overlap): documented in Out of Scope line 168
- F-2 (NaN confidence): documented in Out of Scope line 169

All round 1 P2+ findings CLOSED.

## Findings

### F-1: `tests/test_finding_merge.py` claim could be more explicit
**Severity:** P2
Spec asserts "same-severity findings" without citing the `_finding()` helper default of `Severity.MEDIUM`.

### F-2: Overlap window contraction is technically more visible under severity-first
**Severity:** P3
Out of Scope wording says "not worsened" — technically the winning finding may have a narrower span under severity-first vs confidence-first, changing which subsequent findings survive.

### F-3: No test covers CRITICAL as `nxt` beating earlier INFO
**Severity:** P2
Regression test arranges CRITICAL at [0,10) (sorts first as `current`). No test where CRITICAL arrives as `nxt` via later position.start, exercising the `nxt_rank < cur_rank` branch.

### F-4: `test_merge_high_beats_medium_regardless_of_conf` is semantically redundant with regression test
**Severity:** P4
Exercises same code path at different severity tier. Keep it but also add F-3 test.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 1 | P4: 1

STATUS: GREEN
