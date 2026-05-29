# Conventions Review — Round 1

### F-1 (P1): Existing adversarial tests will break
`test_injection_evasion.py` has `test_nul_byte_not_flagged_by_binary_pattern` (asserts NUL NOT flagged) and `test_json_depth_counts_brackets_inside_strings` (asserts depth > 10). Both assert current buggy behavior. After SYN-04/SYN-05 fixes, both fail. File not in "Files to change" table.

### F-2 (P3): Inline clamp vs helper — undocumented brief deviation
Brief proposed `_clamp_confidence()` helper. Spec uses inline `max/min`. Matches existing llama_firewall pattern but not documented as intentional.

### F-3 (P2): D2 contains self-contradicting deliberation text
Lines 60-63 read like draft notes ("Actually, on review..."). Spec should state the chosen approach once.

### F-4 (P3): Dead code retention of `_resolve_overlaps()`
PET-30 removed dead code for the same reason. Keeping it creates re-enablement risk.

### F-5 (P4): Stale line reference L124 vs L132

### F-6 (P4): Brief's test directory not noted

### F-7 (P2): Missing `__init__.py` in syntactic test dir
Sibling directories (`tests/adversarial/frequency/`) have `__init__.py`. Inconsistent.

P0: 0 | P1: 1 | P2: 2 | P3: 2 | P4: 2

STATUS: RED P0=0 P1=1 P2=2 P3=2 P4=2
