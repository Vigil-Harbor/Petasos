# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: ValueError from anonymize() silently swallowed by pipeline (P2)
Pipeline's `except Exception` at L444 catches the ValueError and appends it to errors as a string. PII remains unsanitized. Spec should acknowledge this interaction explicitly.

### F-2: Config guard bypass via whitespace-only hash_key (P2)
`hash_key=" "` passes `not self.hash_key` since whitespace strings are truthy. HMAC with a single-space key is nearly as degenerate as empty. Covered by Out of Scope ("any non-empty string accepted") but worth a note.

### F-3: `assert hash_key` in _anonymize_engine_path() stripped by python -O (P1)
Defense-in-depth guard disappears under optimization. Replace with explicit raise.

### F-4: Direct callers of _anonymize_engine_path() bypass anonymize() guard (P3)
Internal function with `_` prefix. Low risk since operator `validate()` fires, but assert is the only pre-operator guard.

### F-5: No pipeline-level integration test for empty hash_key (P2)
All tests are unit-level. Config guard catches it, but no integration test verifies.

### F-6: Spec line references slightly off (P4)
All within +/-1 line. No functional impact.

### F-7: `not hash_key` doesn't distinguish type errors from empty strings (P3)
Non-string falsy values get a misleading error message. Functionally safe since API is typed.

### F-8: operator validate() timing clarification (P3)
validate() fires during engine.anonymize(), not at OperatorConfig construction. Spec is accurate; clarification only.

## Summary
P0: 0 | P1: 1 | P2: 3 | P3: 3 | P4: 1

STATUS: RED P0=0 P1=1 P2=3 P3=3 P4=1
