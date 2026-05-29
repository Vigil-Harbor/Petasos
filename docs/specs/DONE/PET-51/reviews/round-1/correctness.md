# Correctness Review -- round 1

## Closure of round N-1 findings
N/A -- round 1

## Findings

### F-1: Stale line-number anchor for confidence floor filtering
**Severity:** P2
**Where:** spec.md:40 (Decision: "No minimum confidence filter in merge")
**Claim:** "Confidence floor filtering is a separate stage (`pipeline.py` L381-386, profile-driven)."
**Why this is wrong:** The confidence floor filtering is currently at `petasos/pipeline.py` L390-396 (Stage 5b comment at L390, conditional block at L391-396). Lines 381-386 contain the scanner fan-out result aggregation. The anchor was likely accurate at the time of the brief but is now stale.
**Suggested fix:** Change `L381-386` to "Stage 5b in `_inspect_inner`" or update line numbers.

### F-2: Pseudocode uses direct indexing while noting `.get()` fallback separately
**Severity:** P4
**Where:** spec.md:62-63 (Design: "New overlap resolution" pseudocode)
**Claim:** The pseudocode uses `_SEVERITY_RANK[nxt.severity]` (direct index), while the concrete code block uses `_SEVERITY_RANK.get(nxt.severity, 999)`.
**Why this is a nit:** The spec acknowledges this at line 74. Internally consistent when read as a whole.
**Suggested fix:** Align the pseudocode to use `.get(severity, 999)` for consistency.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 1

STATUS: GREEN
