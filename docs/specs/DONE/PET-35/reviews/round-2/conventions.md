# PET-35 Conventions Review — Round 2

## Closure of round 1 findings
All round 1 conventions findings CLOSED. F-1 (P2 casefold/lower inconsistency) closed by Decision 6 + Design §3. F-2/F-3/F-4 (P3 category-c surfacing) closed with no action needed.

## Findings

### F-1: "Files to leave alone" references non-existent profiles.py (P4)
Should be `profiles/__init__.py` or removed since it's already in "Files to change".

### F-2: Decision 6 profiles harmonization is a category-c addition (P3)
Brief doesn't mention profiles. Surfaced per protocol. No action needed.

### F-3: Decision 7 deferred alias-key casefolding is a category-c addition (P3)
Not in brief. Surfaced per protocol. No action needed.

### F-4: Decision 5 GUARD-03 preservation is a category-c addition (P3)
Brief code snippet omits GUARD-03. Spec correctly restores it. Surfaced per protocol.

### F-5: Test command uses hardcoded Windows Python path (P4)
CLAUDE.md says `pytest`. Spec uses full path. Pre-existing divergence across specs.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 2

STATUS: GREEN
