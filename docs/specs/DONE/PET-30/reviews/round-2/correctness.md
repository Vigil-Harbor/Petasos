# PET-30 Correctness Review — Round 2

## Closure of round 1 findings
All 8 round-1 correctness findings (F-1 through F-8, all P2–P4) confirmed CLOSED.
All 10 round-1 edge-cases findings confirmed CLOSED.

## Findings

### F-1: Stale line-number anchor for `_derive_tier()` in guard.py [FALSE POSITIVE]
**Severity:** P1 (claimed) → **VOID**
**Where:** spec Design section 12
**Claim:** PET-36 shifted `_derive_tier()` from L170 to L186.
**Verification:** `grep -n "def _derive_tier" guard.py` → L170. PET-36 is still in spec stage (untracked files in `docs/specs/TODO/PET-36.*`), not merged. Line numbers are correct.
**Status:** FALSE POSITIVE — no fix needed.

### F-2: Brief section 5 retains `state.terminated` but spec removes it
**Severity:** P2
The spec's removal is logically correct but diverges from the brief's proposed code. Should be documented.
**Suggested fix:** Add a note in Design section 12.

### F-3: Conventions review file missing from round 1
**Severity:** P3
**Status:** File exists at `docs/specs/TODO/PET-30.reviews/round-1/conventions.md`. Reviewer ran in worktree that didn't have the file. FALSE POSITIVE.

## Summary (corrected)
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 0

STATUS: GREEN
