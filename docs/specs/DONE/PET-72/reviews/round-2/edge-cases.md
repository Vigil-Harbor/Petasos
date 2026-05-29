# PET-72 Edge-Cases Review -- Round 2

## Closure of round 1 findings
All round 1 P1/P2 findings CLOSED:
- F-1 (P2): NaN/inf tests added (#10, #11), behavior documented in Decision 2
- F-2 (P1): **kwargs handling added with VAR_KEYWORD check
- F-3 (P2): "never throws" scope noted in section 6
- F-4 (P2): Position float deferred (P3), mypy catches statically
- F-5 (P3): Shallow MappingProxyType documented in Decision 1
- F-6 (P2): hasattr wrapped in try/except
- F-7 (P2): Positive test #12 added
- F-8 (P3): inspect.signature wrapped in try/except
- F-9 (P3): Acknowledged, existing behavior
- F-10 (P2): TYPE_CHECKING import fixed

## Findings

### F-1: MappingProxyType pass-through does not sever underlying dict reference (P3)
Pre-wrapped MappingProxyType skips copying. Caller retaining the backing dict could mutate through the proxy view. Acceptable since the only producer creates dicts in-place.

### F-2: _validate_scanner rejects async callable objects (P3)
inspect.iscoroutinefunction returns False for instances with async __call__. Acceptable since Scanner protocol mandates plain async method.

### F-3: Keyword-only text parameter accepted but _scan_one calls positionally (P3)
Validator checks name presence, not parameter kind. Mypy catches protocol mismatch.

### F-4: No test for **kwargs scanner bypass path (P2)
Round 1 F-2 fix added code but no test. Scanner with async def scan(self, text, **kwargs) should have a positive test.

### F-5: No test for inspect.signature failure path (P2)
Round 1 F-8 fix added code but no test.

### F-6: No test for property-exception wrapping (P2)
Round 1 F-6 fix added code but no test.

### F-7: ScanFinding.confidence accepts non-float types (P3)
bool(True) passes comparison. Same class as Position float deferral.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 4 | P4: 0

STATUS: GREEN
