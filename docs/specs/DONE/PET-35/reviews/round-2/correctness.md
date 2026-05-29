# PET-35 Correctness Review — Round 2

## Closure of round 1 findings
All round 1 correctness findings (F-1 P3 duplicate test, F-2 P3 casefold/lower mismatch, F-3 P4 line reference) CLOSED. See closure table in review body.

## Findings

### F-1: "Files to leave alone" references nonexistent `petasos/premium/profiles.py` (P4)
No file `petasos/premium/profiles.py` exists. Profile code lives in `petasos/premium/profiles/__init__.py`, which is listed in "Files to change". The "leave alone" entry uses shorthand.

### F-2: Removal of final `strip()` changes behavior for directly-constructed profiles with whitespace-padded alias values (P3)
Final `strip()` in current code operates on resolved alias value, not original input. Parse-time stripping handles JSON profiles, but direct construction (test-only) may have whitespace in values.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 1 | P4: 1

STATUS: GREEN
