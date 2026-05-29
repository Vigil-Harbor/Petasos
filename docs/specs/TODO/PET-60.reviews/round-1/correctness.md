# Correctness Review — Round 1

### F-1 (P0): `_compute_safe` early return at `ml_total == 0` bypasses `syntactic_error`
The spec's D5 pseudo-code places the `syntactic_error` check inside the fail-mode branches, but `pipeline.py:115-116` has `if ml_total == 0: return safe` which fires first when only MinimalScanner is configured. The `syntactic_error` flag is never consulted.

### F-2 (P0): Test #14 contradicts D2 design
D2 says "trust pre-merged findings" (non-overlapping). Test #14 says "Two overlapping findings → both applied." Applying overlapping findings in replace mode produces garbled text. Internal contradiction.

### F-3 (P1): Stale line reference for llama_firewall.py (L124 vs L132)
The confidence clamp is at L132, not L124. PET-62 commit shifted lines.

### F-4 (P2): Brief's `tests/adversarial/scanner/` not addressed
Brief expected scanner-specific adversarial tests there. Spec places SCAN-02 tests in unit test files. Reasonable but undocumented.

### F-5 (P2): Public `anonymize()` loses overlap protection for direct callers
D6 says "direct callers should pass pre-merged" but no docstring update, no assertion, no test.

### F-6 (P3): Inline clamp vs helper — undocumented brief deviation

P0: 2 | P1: 1 | P2: 2 | P3: 1

STATUS: RED P0=2 P1=1 P2=2 P3=1
