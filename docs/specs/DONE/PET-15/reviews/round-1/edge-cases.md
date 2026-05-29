# Edge-Cases Review — Round 1

## Findings

### F-1: FlakyMLScanner scan signature lacks type annotations — mypy --strict failure (P1)
The spec's code samples for fake scanners omit type annotations. Under `mypy --strict` (`--disallow-untyped-defs`), this fails. The Done-when gate requires `mypy --strict .` clean.

**Fix:** Add full type annotations to fake scanner code samples.

### F-5/F-8: Chain payload `you are now` substring triggers injection independently (P1)
Same root cause as correctness F-1. The `you-are-now` pattern matches the unbroken substring, producing a HIGH finding and `safe=False` even pre-fix. The baseline test xfails from day one without documenting the vulnerability. Cascades to test 2 assertions (would XPASS immediately since injection findings present via `you-are-now`).

### F-2: Test 3 pre-fix behavior path not explicitly stated (P2)
The dual-path assertion structure is confusing without a note about pre-fix behavior.

### F-3: Test 3 constructs MinimalScanner directly vs. Pipeline profile hook path (P2)
The chain attack uses profile suppression through `_premium_profile_hook`, but the test constructs `MinimalScanner` directly. Pragmatic (avoids JWT) but tests a different code path.

### F-4: Importing underscore-prefixed `_INJECTION_RULE_IDS` (P3)
### F-6: `_compute_safe` name constraint not documented (P3)  
### F-9: Test 5 may be partially redundant with test 4 (P3)
### F-7: asyncio_mode="auto" note (P4)
### F-11: No test for invisible-char escalation pathway (P3)

## Summary
P0: 0 | P1: 2 | P2: 2

STATUS: RED P0=0 P1=2 P2=2
