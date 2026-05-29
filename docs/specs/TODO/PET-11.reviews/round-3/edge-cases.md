# Edge-Cases Review -- round 3

## Closure of round 2 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P1) | Happy-path escalation tier2 fragile | CLOSED | spec v3 line 139: explicit single-pattern input, exact arithmetic 30.0 |
| F-2 (P3) | Benchmark event loop resource leak | OPEN | P3 -- no try/finally added |
| F-3 (P2) | Mock PII findings need position | CLOSED | spec v3 line 154: Position requirement explicit |
| F-4 (P2) | Rate limiting assertion wrong metric | CLOSED | spec v3 line 171: suppressed_count with distinction |
| F-5 (P3) | Benchmark frequency state accumulates | OPEN | P3 -- fixed session_id still used |
| F-6 (P3) | Audit event finding_count assertion | CLOSED | spec v3 line 152: finding_count >= 1 |
| R1 F-10 (P3) | Empty-string input | OPEN | P3 informational |
| R1 F-11 (P2) | No concurrent E2E test | OPEN | P2 -- covered by existing tests |
| R1 F-12 (P2) | Callback exception not in E2E | OPEN | P2 -- covered by unit tests |
| R1 F-13 (P3) | Checklist no automated verification | OPEN | P3 -- documentation artifact |

## Findings

### F-1: MinimalScanner fires encoding rule on zero-width input -- finding count narrative incomplete
**Severity:** P2
**Where:** spec lines 139, 149, 152
**Edge case:** Zero-width input triggers both `injection.ignore-previous` AND `encoding.invisible-chars`. Score unaffected (encoding weight = 0.0) but spec narrative only accounts for 1 MinimalScanner finding when 2 are produced.
**Suggested fix:** Note that MinimalScanner produces 2 findings for zero-width injection input.

### F-2: Mock PII scanner rule_id format determines anonymization entity type label
**Severity:** P2
**Where:** spec lines 117-118, 153-154
**Edge case:** `_recover_entity_type(rule_id)` extracts entity type from rule_id. Spec doesn't specify mock PII rule_id. Example `<PERSON_1>` implies specific format.
**Suggested fix:** Specify `rule_id="petasos.presidio.person"` for mock PII findings.

### F-3: Happy-path test input zero-width char may be silently stripped by editor
**Severity:** P2
**Where:** spec line 139
**Edge case:** Invisible U+200B in spec text is fragile. If stripped, normalization assertion fails.
**Suggested fix:** Specify construction explicitly: `"​" + "ignore previous instructions"`.

### F-4: Benchmark 3c frequency state accumulates (carried from round 2)
**Severity:** P3
**Where:** spec lines 247-256
**Suggested fix:** Use unique session_id per iteration.

### F-5: Benchmark event loop resource leak (carried from round 2)
**Severity:** P3
**Where:** spec lines 215-222, 247-256
**Suggested fix:** Wrap in try/finally.

### F-6: Pipeline passes raw text to MinimalScanner -- narrative slightly misleading
**Severity:** P3
**Where:** spec lines 147-148
**Suggested fix:** Add note that MinimalScanner receives raw text and normalizes internally.

### F-7: Benchmark 3c uses default weights vs E2E custom weights -- undocumented
**Severity:** P3
**Where:** spec lines 244-249 vs 128-129
**Suggested fix:** Document the difference or address F-4.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 4 | P4: 0

STATUS: GREEN
