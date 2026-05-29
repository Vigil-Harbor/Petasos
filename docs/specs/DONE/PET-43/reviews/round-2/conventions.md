# Conventions Review — Round 2

## Closure table
All round 1 findings CLOSED:
- F-1 (P2): D3 deprecation → CLOSED (no annotation, rationale provided)
- F-5 (P2): Literal invisible chars → CLOSED (chr() form adopted)
- F-6 (P2): INVISIBLE_CHARS import → CLOSED (conditional instruction added)

## Findings

### F-1 (P3): chr() style in new code vs literal chars in existing RTL_OVERRIDES/INVISIBLE_CHARS
Mixed style within normalize.py. chr() is safer; note that it's preferred going forward.

### F-2 (P3): D3 overrides brief's "preserve as deprecated" without "Brief deviation:" label
Brief DCF bullet 3 says "preserve as deprecated." Spec D3 says "no deprecation annotation." Could add a deviation label for traceability.

### F-3 (P4): Test #10 conditional import correctly resolves — import stays
Not a defect. The conditional handles it.

### F-4 (P3): D6 brief correction is well-documented (category c addition)
Flagged for drift-check visibility only.

P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 1 (+ 3 more P4 nits)

STATUS: GREEN
