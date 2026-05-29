# Edge-Cases Review -- round 1

## Findings

### F-1: Dropping the loser in asymmetric severity contracts the overlap window (transitive overlap chains)
**Severity:** P1
**Where:** spec.md:109-116 (the "After" code block)
**Edge case:** When a lower-severity finding that extends beyond the winner's position is dropped, the effective overlap window contracts. Subsequent findings that would have overlapped with the dropped finding are treated as non-overlapping and spuriously survive.
**Example:** A at [0,10) CRITICAL/0.5, B at [5,15) INFO/0.99, C at [8,20) HIGH/0.8. After A beats B, current=A (end=10). C.start(8) < A.end(10) so overlap detected, A beats C. But if D at [12,25) exists, D.start(12) < A.end(10) is False so D survives as non-overlapping — even though D overlaps with the dropped B and C.
**Note:** This is a pre-existing issue in the greedy merge algorithm, not introduced by this spec.
**Suggested fix:** Document as known limitation or extend effective overlap end on drop.

### F-2: NaN confidence breaks all comparison branches silently
**Severity:** P1
**Where:** spec.md:112-114 (confidence comparisons)
**Edge case:** If a scanner returns `confidence=float('nan')`, all comparisons (`>`, `==`) return False per IEEE 754. The code falls through all branches and nxt is silently dropped.
**Note:** Pre-existing issue — `ScanFinding.confidence` is bare `float` with no validation.
**Suggested fix:** Add a NaN guard or document the precondition.

### F-3: Negative or >1.0 confidence produces correct but undocumented behavior
**Severity:** P3

### F-4: Single positioned finding — loop skips correctly
**Severity:** P4 (confirmed correct)

### F-5: Sort stability for equal-start-position findings
**Severity:** P2
**Where:** spec.md:127
**Edge case:** Equal position.start findings retain insertion order (scanner return order). Severity-first makes different-severity cases symmetric, but equal-severity equal-confidence case is order-dependent (cosmetic — both survive).

### F-7: Test plan does not explicitly verify the "nxt loses" drop path
**Severity:** P2
**Where:** spec.md:136-143
**Suggested fix:** Strengthen `test_merge_high_beats_medium_regardless_of_conf` to verify `len(merged) == 1`.

### F-11: "Keep both" path for equal-severity equal-confidence — overlap window extension
**Severity:** P2 (confirmed correct, no data loss)

### F-12: Test file rename creates gap if done incorrectly
**Severity:** P3 (caught by test suite)

## Summary
P0: 0 | P1: 2 | P2: 3 | P3: 2 | P4: 5

STATUS: RED P0=0 P1=2 P2=3 P3=2 P4=5
