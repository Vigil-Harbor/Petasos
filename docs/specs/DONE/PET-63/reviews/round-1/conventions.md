# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Config-level hash_key guard is a silent spec addition (P3)
Brief scopes three changes in presidio.py with six tests. Spec adds D4 (config.py change) and test 8 (test_config.py). Rationale in D4 is sound but this is a category-c addition the human drift-check should see.

### F-2: Bare assert precedent conflict with PET-10 (P3)
PET-10 review flagged bare assert as P1. Context differs (defense-in-depth vs primary check, existing assert precedent in presidio.py), but spec should acknowledge the PET-10 precedent.

### F-3: Line-number references accurate (P4)
All references verified against source. No violations.

### F-4: "Never throw" boundary correctly distinguished (P4)
Consistent with PET-8, PET-36 established pattern.

### F-5: Test class placement follows existing structure (P4)
New tests in existing TestAnonymizeHash class. Naming convention matches.

### F-6: No premature abstraction (P4)
All changes are minimal inline edits to existing code.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 2 | P4: 4

STATUS: GREEN
