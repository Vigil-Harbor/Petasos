# Conventions Review -- Round 1

## Findings

### F-1: Spec documents already-shipped PET-30 code as PET-34 work (P1)
All code shipped under PET-30 (commit b8f9ad4). Spec has all Done When boxes checked but lives in TODO/. Unclear what PET-34 adds beyond PET-30.

### F-2: Test count mismatch -- 21 vs actual 25 (P2)
Same as correctness F-4. Config validation class has 5 sub-tests.

### F-3: D3 reset/force_reset departure from brief not flagged (P2)
Brief says reset() clears; spec says reset() preserves. Sound but silent change.

### F-4: D6 independent config field replaces brief's max_sessions * 2 without flagging (P2)
Brief proposed `max_sessions * 2` and name `max_terminated_sessions`. Spec uses independent `max_terminated_tombstones` with default 10,000.

### F-5: D1 OrderedDict vs set+deque -- well-rationalized (P3)
Noted for visibility. D1 provides good rationale.

### F-6: Wiki state.md uses `_terminated_tombstones` vs code's `_terminated_ids` (P2)
Wiki naming mismatch. Spec and code agree; wiki is wrong.

### F-7: Brief's test file locations differ from spec's (P3)
Brief proposed `tests/unit/premium/` paths; spec uses actual flat layout. Not flagged.

### F-8: Done When checkboxes all checked in TODO spec (P3)
Lifecycle issue — TODO specs should have unchecked boxes.

## Summary
P0: 0 | P1: 1 | P2: 4 | P3: 3

STATUS: RED P0=0 P1=1 P2=4 P3=3
