# PET-72 Correctness Review -- Round 1

## Findings

### F-1: Removing TYPE_CHECKING block leaves unused TYPE_CHECKING import -- lint failure (P1)
`TYPE_CHECKING` imported at `_types.py:5`. After removing the `if TYPE_CHECKING:` block, `TYPE_CHECKING` itself becomes unused. `ruff check` flags F401.
**Fix:** Remove `TYPE_CHECKING` from the `typing` import line.

### F-2: Brief Done-when #1 unmapped -- ScanFinding dict fields (P2)
Brief says "Mutating a dict field on a constructed ScanFinding raises TypeError" but ScanFinding has no dict fields. Spec correctly scopes TYP-02 to PipelineResult.premium_features and documents the drift in Deferred section.

### F-3: Missing explanation of why import promotion is needed (P3)
Spec does not explain why MappingProxyType needs runtime import (PEP 563 makes annotations lazy strings; TYPE_CHECKING sufficed for annotations alone).

### F-4: validate_scanner not added to __init__.py exports -- intentional but unstated (P4)
Spec doesn't state whether validate_scanner is public or private API.

## Summary
P0: 0 | P1: 1 | P2: 1 | P3: 1 | P4: 1

STATUS: RED P0=0 P1=1 P2=1 P3=1 P4=1
