# Correctness Review — Round 2

## Closure table
All round 1 P0/P1 findings CLOSED (20 total across all lenses).

## Findings

### F-1 (P1): D2 alignment incomplete — equal-severity-equal-confidence case
`merge_findings()` keeps both findings when sev and conf are equal. The proposed `_resolve_overlaps()` silently drops the second. The spec claims alignment but the equal case diverges.

### F-2 (P4): Line ref "L209-212" vs actual L209-211

### F-3 (P2): Missing `__init__.py` in syntactic dir — conventions reviewer clarified this is NOT the repo convention (only `frequency/` has one, anomaly)

### F-4 (P3): `_SEVERITY_RANK` import vs local — ambiguous

### F-5 (P3): D2 brief deviation not labeled

P0: 0 | P1: 1 | P2: 1 | P3: 2 | P4: 1

STATUS: RED P0=0 P1=1 P2=1 P3=2 P4=1
