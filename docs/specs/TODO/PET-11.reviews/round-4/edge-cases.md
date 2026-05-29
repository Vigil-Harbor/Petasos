# Edge-Cases Review -- round 4

## Closure of round 3 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P2) | MinimalScanner fires encoding rule -- finding count narrative incomplete | CLOSED | spec v4: narrative updated to show 2 findings (injection + encoding) |
| F-2 (P2) | Mock PII scanner rule_id format determines anonymization entity type label | CLOSED | spec v4: specifies `rule_id="petasos.presidio.person"` |
| F-3 (P2) | Happy-path test input zero-width char may be silently stripped by editor | CLOSED | spec v4: explicit `"​"` escape construction |
| F-4 (P3) | Benchmark 3c frequency state accumulates | OPEN | P3 -- informational |
| F-5 (P3) | Benchmark event loop resource leak | OPEN | P3 -- informational |
| F-6 (P3) | Pipeline passes raw text to MinimalScanner -- narrative slightly misleading | CLOSED | spec v4: note added |
| F-7 (P3) | Benchmark 3c uses default weights vs E2E custom weights | OPEN | P3 -- informational |

## Findings

### F-1: Mock PII position offsets should target normalized_text not raw text
**Severity:** P2
**Where:** spec E2E happy-path setup
**Edge case:** Position offsets in mock PII findings reference raw input text. After normalization, character positions shift (zero-width chars removed). If assertions check position against `sanitized_content` (which is based on normalized text), offsets may be off by the number of stripped characters.
**Suggested fix:** Document that mock PII position offsets target the normalized text, or adjust offsets to account for normalization.

### F-2: Benchmark 3c frequency state accumulates (carried from round 3)
**Severity:** P3
**Where:** spec benchmark 3c
**Suggested fix:** Use unique session_id per iteration.

### F-3: Benchmark event loop resource leak (carried from round 3)
**Severity:** P3
**Where:** spec benchmark setup
**Suggested fix:** Wrap in try/finally.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 0

STATUS: GREEN
