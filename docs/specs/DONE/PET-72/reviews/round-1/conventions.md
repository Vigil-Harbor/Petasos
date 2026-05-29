# PET-72 Conventions Review -- Round 1

## Findings

### F-1: __init__.py contradicts established adversarial test convention (P2)
8 of 9 adversarial subdirectories omit __init__.py. Only frequency/ has one (historical anomaly).

### F-2: validate_scanner public naming without __init__.py export (P2)
Public name without export, or should be private (_validate_scanner) matching _is_missing_package pattern.

### F-3: import inspect placement not specified (P4)
Spec doesn't state where `import inspect` goes relative to existing imports.

### F-4: Negative position start check is spec addition beyond brief (P3)
Brief says `if self.start > self.end`; spec adds `if self.start < 0`. Reasonable but undocumented addition.

### F-5: Zero-length position validity is spec addition (P3)
Brief doesn't mention zero-length positions. Spec commits to accepting them.

### F-6: Brief "Files touched" includes test_types.py; spec excludes it (P3)
Spec moves tests to adversarial/types/ which matches PET-14 remediation pattern.

### F-7: PEP 563 interaction documented adequately (P4)
Spec correctly handles the TYPE_CHECKING → runtime import promotion.

### F-8: Test count divergence from brief (P4)
Brief says >= 12; spec has 14. Increase justified by NaN/inf and roundtrip tests.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 3 | P4: 3

STATUS: GREEN
