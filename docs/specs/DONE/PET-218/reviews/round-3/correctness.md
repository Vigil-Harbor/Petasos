# Correctness Review — round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Spool `rule_id` anchor is the severity keyword | CLOSED | spec § Decision 3 line 70 cites `rule_id=worst.rule_id` at `reference_plugin/__init__.py:2485` and `severity=worst.severity.name` at `:2484`. At `723cdc5` those lines are that call. Test plan line 163 and Done when line 193 keep the shortened-id agreement. |
| correctness | F-2 | `pii_suppressed` counts PII that never blocked | CLOSED | spec § Decision 6 line 98 requires `finding_type == "pii"` and `ref._blocks(finding.severity)`, and no non-pii blocker. Matches the plugin partition at `:2425-2426` (blocking, then non-pii). |
| conventions | F-1 | Spool `rule_id` anchor is the severity keyword | CLOSED | Same fold as correctness F-1 (spec line 70; blob `:2484` severity, `:2485` rule id). |
| conventions | F-2 | `policy_from_cells` does not read only `flagged_high_plus` and `n_eff` | CLOSED | spec § Decision 6 line 102: `wilson95` keeps that pair; `policy_from_cells` gains no helper read and still reads `flagged_high_plus`, `n_eff`, `label`, `stratum`, `family`, and the shortened `rule_histogram`. Matches `scripts/pet200_calibrate.py:546-611` at `723cdc5`. |
| conventions | F-3 | Per-sample reader reimplements `drain_enforcement_events` | CLOSED | spec § Decision 3 lines 55–61 and § Design line 145: offset and cap from `spool_size` / `SPOOL_CAP_BYTES`, parse via `drain_enforcement_events` (`petasos/console/_events.py:183-230`), `attribute_new_events` as the pure filter, no second decoder. |
| conventions | F-4 | Under-30 monotonic failure is a spec-level addition | CLOSED | spec § Decision 3 line 74 names that fail-closed clock outcome as a spec-level addition. The `< 30.0` mechanism matches `_log_ingest_unscanned` at `:1356-1358` and `_INGEST_UNSCANNED_LOG_EVERY_S = _DISARM_LOG_EVERY_S` (`:218`, literal `30.0` at `:182`). |

No `## Deferred — follow-up required` section. `scale_lens` is off; round 2 has no scalability report. Plane tickets were cached: PET-218 (`30fc3612-cb5e-43f8-b6b0-9cf06ed664a5`, Backlog) and PET-219 (`09461d7c-6ddf-4551-9143-b64fcabc851b`, Backlog). Their helper columns are the three null fields in schema 1; the shipped report has no coverage column and no second histogram. Anchors were checked with `git show 723cdc5956d024195b3b3afdde09004618266aa6`, not the diverged worktree. Commits since 2026-09-15 that touch the calibrator or changelog (`7bb508a`, `723cdc5`) are inside that base.

## Findings

No findings.

## Summary

P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
