# Edge-Cases Review — round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Flagged spool rule_id cannot equal parse_top_finding | CLOSED | spec § Decision 3, lines 70–73; § Test plan line 166; § Done when line 196 |
| correctness | F-2 | _BLOCK_RANK anchor is the LOW rank entry | CLOSED | spec § Scope line 23 cites `:379` |
| correctness | F-3 | helper_samples is never defined | CLOSED | spec § Decision 7 lines 115–116 |
| correctness | F-4 | Helper severity tokens are enum names, not Severity values | CLOSED | spec § Decision 6 lines 98–101 |
| edge-cases | F-1 | Banner rule id and spool rule id cannot agree | CLOSED | spec § Decision 3 lines 70–73; § Test plan line 166; § Done when line 196 |
| edge-cases | F-2 | Helper severity tokens are not the finding's runtime type | CLOSED | spec § Decision 6 lines 98–101 |
| edge-cases | F-3 | First ingest_unscanned is suppressed while monotonic is under 30s | CLOSED | spec § Decision 3 lines 76–77; § Test plan lines 168–169 and 174 |
| edge-cases | F-4 | Exit 3 leaves a previous report in place | CLOSED | spec § Decision 4 line 83; § Test plan line 176 |
| conventions | F-1 | _BLOCK_RANK anchor points at the LOW rank entry | CLOSED | spec § Scope line 23 |
| conventions | F-2 | Top-level observation is a report-contract addition | CLOSED | spec § Decision 7 line 117 |
| conventions | F-3 | Exit code 3 is a new CLI contract | CLOSED | spec § Decision 4 lines 82–83 |
| conventions | F-4 | Spool restore does not name the autouse fixture it nests under | CLOSED | spec § Decision 2 line 49 |

## Findings

No findings.

## Summary

Plane PET-218 was retrieved (`30fc3612-cb5e-43f8-b6b0-9cf06ed664a5`, Backlog). Anchors were checked on `723cdc5956d024195b3b3afdde09004618266aa6`. No deferred-findings section is present. Round-1 edges (rule-id agreement, enum severity, monotonic under 30, exit 3 leaving `--out`, autouse nesting, helper_samples) are specified, and the remaining empty, cadence, cap, cleanup, and capture-miss paths fail closed instead of publishing a zero.

P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
