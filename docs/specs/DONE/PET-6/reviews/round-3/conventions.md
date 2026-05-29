# PET-6 Spec Review — Conventions (Round 3)

## Closure of round 2 findings

All findings CLOSED. See closure table in full report.

## Findings

### F-1 (P3): Brief done-when for `petasos:` key not gated in spec done-when
D8 covers the design intent but done-when omits the criterion. Implicitly covered by to_dict/from_dict tests.

### F-2 (P3): Latency benchmarks dropped — rationale provided
Out of Scope line 417. Sound rationale — PET-6 uses mocks.

### F-3 (P4): Wiki filemap says `NormalizeResult` but codebase uses `NormalizedText`
Pre-existing wiki staleness. Will be corrected during post-PET-6 wiki update.

## Summary

P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 1

STATUS: GREEN
