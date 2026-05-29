# PET-35 Conventions Review — Round 1

## Findings

### F-1: casefold/lower inconsistency between guard runtime and profiles construction (P2)
`profiles/__init__.py` L79/L82/L155/L168 use `.lower()` for exempt list and collision checks. The spec's guard runtime uses `.casefold()`. For ASCII identical, but the spec's own Decision 2 motivates casefold for Unicode correctness — one side should match the other.

### F-2: Decision 4 (module-level import) overrides brief's inline import (P3)
Brief shows `import unicodedata` inside the method. Spec moves to module level with explicit rationale. Sound improvement, surfaced per category-c protocol.

### F-3: Decision 1 resolves brief's open question on extraction (P3)
Brief says "either approach acceptable." Spec makes firm choice (direct import, no extraction) with anti-premature-abstraction rationale. Sound decision.

### F-4: Decision 5 (GUARD-03 preservation) adds detail brief didn't specify (P3)
Brief's code snippet omits GUARD-03 check. Spec restores it with casefold migration. Correctly accounts for PET-36 code that landed after brief.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 3 | P4: 0

STATUS: GREEN
