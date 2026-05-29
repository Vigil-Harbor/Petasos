# PET-6 Spec Review — Correctness (Round 2)

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Double normalization | CLOSED | spec line 146: MinimalScanner receives "original raw text" |
| correctness | F-2 | Ambiguous ML scanner text | CLOSED | spec line 150: ML scanners receive "normalized text" |
| correctness | F-3 | BaseException vs Exception | CLOSED | spec lines 38, 158, 177: Exception everywhere |
| correctness | F-4 | Premium hooks **kwargs mismatch | CLOSED | **kwargs removed from prose |
| correctness | F-5 | pii_entities not wired | CLOSED | Deferred section acknowledges |
| correctness | F-6 | Severity ordering misleading | CLOSED | Explicit rank dict, lines 199-206 |
| correctness | F-7 | Direction validation missing | CLOSED | spec line 105 |
| correctness | F-8 | All-or-nothing normalization | CLOSED | Out of Scope + Deferred |
| correctness | F-9-F-12 | P3 items | CLOSED | Acceptable |
| edge-cases | F-1/F-2 | BaseException in inspect/scan_one | CLOSED | Exception everywhere |
| edge-cases | F-3 | Anonymization position mismatch | CLOSED | spec lines 244-246 |
| edge-cases | F-4 | Sweep algorithm ambiguity | CLOSED | Running-winner pattern |
| conventions | F-1-F-4 | P2 advisory items | CLOSED | Deferred section |

## Findings

### F-1 (P1): NormalizedText field name `.has_rtl_override` does not exist
**Section:** Design §4.2, stage 1 (line 144)
The spec says `.has_rtl_override` but the actual field on `NormalizedText` in `_types.py` is `.rtl_overrides_detected`.
**Fix:** Change `.has_rtl_override` to `.rtl_overrides_detected`.

### F-2 (P1): Premium hook placement contradicts stage ordering
**Section:** Design §4.2, stages 6-8
Stage 8 lists all four premium hooks together, but the hook descriptions say frequency and escalation run "after merge, before fail-mode" (between stages 5 and 6). The CLAUDE.md architecture diagram confirms: merge → [Premium] Frequency/Escalation → Anonymize → [Premium] Audit/Alerting. The current stage numbering would place frequency/escalation hooks after anonymization.
**Fix:** Interleave hooks at correct positions or renumber stages.

### F-3 (P2): `_scan_one` code block omits `duration_ms` in error ScanResult
**Section:** Design §4.2, stage 4 (line 159)
All real scanner implementations capture elapsed time even in error paths. The spec's code block defaults to 0.0 — loses observability data.
**Fix:** Add `duration_ms` capture in error path.

### F-4 (P2): Early exit in closed mode underspecified for PipelineResult assembly
**Section:** Design §4.2, stage 3 (line 148)
Specifies `safe=False` but doesn't describe the rest of the PipelineResult fields for the early-exit path.
**Fix:** Add explicit PipelineResult construction for early exit.

## Summary

| Severity | Count |
|----------|-------|
| P0 | 0 |
| P1 | 2 |
| P2 | 2 |

STATUS: RED P0=0 P1=2 P2=2
