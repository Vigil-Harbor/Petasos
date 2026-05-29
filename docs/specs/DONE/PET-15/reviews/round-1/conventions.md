# Conventions Review — Round 1

## Findings

### F-2: Missing @pytest.mark.asyncio in spec's test descriptions (P2)
Every async test in the repo is decorated with `@pytest.mark.asyncio` despite `asyncio_mode = "auto"`. The spec only mentions xfail markers.

### F-3: Spec imports `_INJECTION_RULE_IDS | _ROLE_SWITCH_RULE_IDS` but `_ALL_INJECTION_IDS` already exists (P2)
`minimal.py:98` defines `_ALL_INJECTION_IDS = _INJECTION_RULE_IDS | _ROLE_SWITCH_RULE_IDS`. The brief also uses `_ALL_INJECTION_IDS`. Import the existing constant.

### F-7: `from __future__ import annotations` not mentioned (P2)
Universal repo convention. Every Python file starts with this import.

### F-1: Fake scanner `name` as @property vs class attribute (P3)
### F-4: Scanner class naming (_FlakyMLScanner vs FlakyMLScanner) (P4)
### F-5: FlakyMLScanner raises vs returns error — divergence from sibling test (P3)
### F-6: Test 3 mixes unit-test assertion with integration scope (P3)
### F-8: Module docstring convention not specified (P4)
### F-9: `duration_ms=1.0` diverges from existing pattern (P4)

## Summary
P0: 0 | P1: 0 | P2: 3

STATUS: GREEN
