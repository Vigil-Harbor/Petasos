# PET-72 Conventions Review -- Round 2

## Closure of round 1 findings
All round 1 findings CLOSED:
- F-1 (P2): __init__.py removed, matching majority adversarial convention
- F-2 (P2): Renamed to _validate_scanner (private), no export needed
- F-3 (P4): import inspect placement specified
- F-4 (P3): Decision 4 documents negative-start as spec addition
- F-5 (P3): Zero-length position documented inline
- F-6 (P3): Files to leave alone explains test location
- F-7 (P4): PEP 563 fully documented
- F-8 (P4): Test count divergence noted in Deferred

## Findings

### F-1: Pipeline import should consolidate into existing import block (P2)
Ruff isort would flag a separate `from petasos._types import _validate_scanner` line. Should be added to existing import block at pipeline.py line 12.

### F-2: **kwargs bypass is a silent spec addition (P3)
Brief says "smoke-call signature check" but doesn't mention **kwargs. Reasonable refinement but not flagged as a spec addition.

### F-3: hasattr exception wrapping is a silent spec addition (P3)
Brief doesn't mention property accessor exception wrapping.

### F-4: inspect.signature failure handling is a silent spec addition (P3)
Brief doesn't mention handling inspect.signature failures.

### F-5: Two-loop approach in Pipeline.__init__ (P4)
Separate validation loop before classification loop. Minor but clear for code review.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 1

STATUS: GREEN
