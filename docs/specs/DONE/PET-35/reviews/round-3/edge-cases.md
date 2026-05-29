# PET-35 Edge-Cases Review — Round 3

## Closure of round 2 findings
All round 2 findings CLOSED. F-7 (P1 alias value casefold) closed by Decision 8 + return resolved.strip().casefold().

## Findings

### F-1: GUARD-03 silent-skip failure mode with adversarial profile alias keys (P3)
Profile alias key "Exec" silently never matches casefolded "exec". Safe (no bypass) but operator intent lost. Pre-existing. Decision 7 defers.

### F-2: dict copy of DEFAULT_TOOL_ALIASES on every call (P4)
Pre-existing pattern. MappingProxyType.get() works directly. Performance nit.

### F-3: Combining diacritical marks survive NFKC (P3)
Out of scope. Homoglyph table doesn't cover accent-stripping. Safe direction.

### F-4: No test for GUARD-03 casefold-specific path (P2)
Existing GUARD-03 tests use ASCII, so casefold==lower. Could add a test with eszett to catch casefold/lower regression.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 1

STATUS: GREEN
