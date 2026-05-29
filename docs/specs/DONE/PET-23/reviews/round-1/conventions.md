# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

F-1 (P2): Spec expands scope to pipeline.py and escalation.py beyond brief's "Files touched" — justified (c)-class expansion with explicit rationale.

F-2 (P3): `_HARDCODED_TIER3_FLOOR` naming inconsistent with repo pattern (`_DESCRIPTIVE_NAME`). Suggest `_TIER3_FLOOR_MIN`.

F-3 (P2): TIER3_FLOOR re-export chain (escalation.py, premium/__init__.py) not addressed — runtime guard is sufficient defense but should be acknowledged.

F-4 (P3): deepcopy on frozen+slotted dataclass with MappingProxyType — interaction not verified.

F-5 (P4): Pipeline.config property exposes internal reference — test depends on it.

F-6 (P2): _compute_safe fallback needs logging — matches repo pattern (_logger.warning).

F-7 (P3): Brief done-when divergence correctly documented as (c)-class addition.

F-8 (P4): Test 11 is novel pattern (no precedent for get_type_hints in tests).

F-9 (P2): evaluate_tier() ValueError caught by pipeline error handler but causes escalation to fail-open — consider fail-secure return.

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 3 | P4: 2

STATUS: GREEN
