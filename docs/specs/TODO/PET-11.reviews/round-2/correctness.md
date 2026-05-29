# Correctness Review -- round 2

## Closure of round 1 findings

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 (P0) | PipelineResult.errors does not contain scanner errors | CLOSED | spec v2 lines 165-168: assertion now checks `result.scanner_results` with explicit note that `PipelineResult.errors` only contains premium-hook/anonymization errors |
| F-2 (P1) | Happy path claims "All features show available" but setup omits tool_guard and profiles | CLOSED | spec v2 lines 125-126, 133: config includes `tool_guard_enabled=True` and `profile="general"` |
| F-3 (P1) | Happy path anonymization depends on presidio or redaction_mode override | CLOSED | spec v2 line 127: `redaction_mode="replace"` explicitly set; lines 137-138 explain manual path |
| F-4 (P1) | v1.0.0 tagging dropped from spec done-when | CLOSED | spec v2 Decision 8 (lines 76-78) and done-when item 10 (line 350) |
| F-5 (P3) | Plane ticket not cached in MCP memory | OPEN | Informational -- MCP memory returns 0 results for PET-11 |
| F-6 (P3) | Test file count "20 test files" inaccurate | CLOSED | spec v2 line 54: corrected to "18 test files" with explanation |
| F-7 (P2) | Benchmark valid_key as bare variable not fixture arg | CLOSED | spec v2 line 243: `def test_benchmark_full_pipeline(benchmark, valid_key):` |
| F-8 (P2) | MockMLScanner name collision | CLOSED | spec v2 lines 176-204: configurable `name` parameter; failure path uses distinct names |

## Findings

### F-1: Spec's frequency weight arithmetic claim is inaccurate but assertion is correct
**Severity:** P2
**Where:** spec line 139
**Claim:** "a single injection-bearing message triggers 2-3 rules (score 40-60), which combined with mock.ml weight crosses tier2_threshold=25.0 but stays below tier3_threshold=50.0 on the first call"
**Why this is wrong:** For input "ignore previous instructions", MinimalScanner fires exactly 1 injection rule (`petasos.syntactic.injection.ignore-previous`). With weight 20.0 per `petasos.syntactic.injection.*`, plus mock ML scanner's 1 finding (`mock.ml.threat`) at weight 10.0, total score is 30.0 -- not "40-60." The tier2 assertion holds (30.0 >= 25.0, 30.0 < 50.0). The arithmetic narrative is misleading but the test outcome is correct.
**Suggested fix:** Change "triggers 2-3 rules (score 40-60)" to "triggers 1 injection rule at weight 20.0, plus mock.ml at weight 10.0, for a total of 30.0".

### F-2: Anonymization label format in spec does not match code
**Severity:** P4
**Where:** spec line 154
**Claim:** "PII entity text is replaced with type labels (e.g., `<PERSON>`)"
**Why:** The `_anonymize_manual_path` function produces `<ENTITY_TYPE_N>` (e.g., `<PERSON_1>`), not `<PERSON>`. The "e.g." qualifier softens it. The assertion (`sanitized_content is not None`) does not depend on label format.
**Suggested fix:** Change example to `<PERSON_1>`.

### F-3: Plane ticket not cached in MCP memory
**Severity:** P3
Informational -- does not block review.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 1 | P4: 1

STATUS: GREEN
