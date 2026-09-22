# Conventions Review — round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Spool `rule_id` anchor is the severity keyword | CLOSED | spec § Decision 3 line 70 cites `rule_id=worst.rule_id` at `reference_plugin/__init__.py:2485` and `severity=worst.severity.name` at `:2484`. At `723cdc5` those lines are that call. The shorten-rule fold stays at the agreement row (line 67), the histogram sentence (line 71), § Design line 145, § Test plan line 163, and § Done when line 193. |
| correctness | F-2 | `pii_suppressed` counts PII that never blocked | CLOSED | spec § Decision 6 lines 98–99 require `finding_type == "pii"` and `ref._blocks(finding.severity)`, and state that a LOW or MEDIUM `pii` finding is not a suppressed banner. `_blocks` is `reference_plugin/__init__.py:382-388` at `723cdc5`. |
| conventions | F-1 | Spool `rule_id` anchor is the severity keyword | CLOSED | Same fold as correctness F-1 (spec § Decision 3 line 70). |
| conventions | F-2 | `policy_from_cells` does not read only `flagged_high_plus` and `n_eff` | CLOSED | spec § Decision 6 line 102: `policy_from_cells` does not gain a read of the three helper fields and still reads `flagged_high_plus`, `n_eff`, `label`, `stratum`, `family`, and the shortened `rule_histogram` for the per-rule flood. That matches `policy_from_cells` at `scripts/pet200_calibrate.py:546-611` (`723cdc5`), including the `count / n_eff >= 0.03` loop at lines 602–610. `wilson95` stays on `flagged_high_plus` and `n_eff`. |
| conventions | F-3 | Per-sample reader reimplements `drain_enforcement_events` | CLOSED | spec § Decision 3 lines 55–62 take the offset from `spool_size` (`petasos/console/_events.py:183-188`), parse with `drain_enforcement_events` (`:191-230`), and keep `attribute_new_events` as the pure filter. `spool_truncated` stays because drain treats `size <= offset` as no events (`:207-208`). § Design line 145 repeats the drain input. No second UTF-8/JSONL decoder. |
| conventions | F-4 | Under-30 monotonic failure is a spec-level addition | CLOSED | spec § Decision 3 line 74 names that fail-closed clock outcome as a spec-level addition so a young monotonic clock is not treated as cadence agreement. |
| edge-cases | — | No round-2 findings | CLOSED | `edge-cases.md` findings section is empty. Nothing to reopen. |

No `## Deferred — follow-up required` section. `scale_lens` is off; no scalability report was scored. Plane memory was available: PET-218 (`30fc3612-cb5e-43f8-b6b0-9cf06ed664a5`, Backlog) and PET-219 (`09461d7c-6ddf-4551-9143-b64fcabc851b`, Backlog). Anchors were checked with `git show 723cdc5956d024195b3b3afdde09004618266aa6`, not the diverged worktree. The monotonic fail-closed rule, exit code 3, and the `observation` field remain labeled additions already closed in earlier rounds; they are not new drift.

## Findings

No findings.

## Summary

P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
