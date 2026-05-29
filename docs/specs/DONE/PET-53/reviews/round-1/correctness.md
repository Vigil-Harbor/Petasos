# Correctness Review -- round 1

## Findings

### F-1: Test 10 violates PetasosConfig validation constraint
**Severity:** P0
`alert_ring_buffer_capacity=10, alert_cross_session_burst_count=15` violates `config.py:305-311` which enforces `burst_count <= ring_buffer_capacity`. Test is not constructible as written.

### F-2: Spec Stage 11 line-range anchor is incomplete
**Severity:** P2
"L509-511" should be "L509-513" (misses except/append lines).

### F-3: Section 2 and Section 3 have conflicting __init__ line anchors
**Severity:** P2
Section 2 says add `_last_callback_error` "after L30" but Section 3 removes L30.

### F-4: Import ordering — `import logging` placement
**Severity:** P4
Alphabetically `logging` before `time` is correct. `ruff` will reorder.

### F-5: Brief says `set()` but spec uses `dict[str, float]`
**Severity:** P3
Acknowledged as spec-level improvement. D4 rationale is sufficient.

### F-6: Adversarial conftest has no premium-activated fixture
**Severity:** P2
`tests/adversarial/conftest.py` provides `minimal_pipeline` and `degraded_pipeline` — neither activates premium. Tests 1-9 need premium.

## Summary
P0: 1 | P1: 0 | P2: 3 | P3: 1 | P4: 1

STATUS: RED P0=1 P1=0 P2=3 P3=1 P4=1
