# Correctness Review -- round 2

## Closure of round 1 findings
All 5 round 1 findings CLOSED with evidence.

## Findings

### F-1: Tests #5 and #6 do not exercise the claims-construction guard they document
**Severity:** P3
**Where:** spec lines 171-172
PyJWT catches `float("inf")` and `iat=10**18` during decode, before the new claims-construction try/except. Tests are valid contract tests but the "Finding: LIC-07" attribution is misleading. Only tests #4 and #7 exercise the new guard directly.

### F-2: Spec byte counts verified
**Severity:** P4
116 bytes (CRLF), 113 bytes (LF) are both correct.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 1

STATUS: GREEN
