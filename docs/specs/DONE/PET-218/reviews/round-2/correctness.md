# Correctness Review — round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | Flagged spool `rule_id` cannot equal `parse_top_finding` | CLOSED | spec § Decision 3 lines 70 and 73–74; § Test plan line 166; § Done when line 196. Agreement is `shorten_rule_id(event["rule_id"])` against the banner id, severity strings equal, raw strings not required to match. Planted pair is spool `petasos.syntactic.injection.ignore-previous` and banner `injection.ignore-previous`, both `HIGH`. |
| correctness | F-2 | `_BLOCK_RANK` anchor is the LOW rank entry | CLOSED | spec § Scope line 23 cites `:379`. At `723cdc5` that line is `_BLOCK_RANK = _SEVERITY_RANK[Severity.HIGH]`. |
| correctness | F-3 | `helper_samples` is never defined | CLOSED | spec § Decision 7 lines 115–116. `helper_samples` increments once per agreed capture, including all-zero marks; a gap leaves it unchanged; `helper_samples == n` after a full cell; null is only the direct `_finalize_cell` view. |
| correctness | F-4 | Helper severity tokens are enum names, not `Severity` values | CLOSED | spec § Decision 6 lines 99 and 101. Compare `Severity.MEDIUM` / `HIGH` / `CRITICAL`; `.value` and the bare string `"MEDIUM"` are rejected; `_blocks` gets the enum member. |
| edge-cases | F-1 | Banner rule id and spool rule id cannot agree | CLOSED | Same fold as correctness F-1. |
| edge-cases | F-2 | Helper severity tokens are not the finding's runtime type | CLOSED | Same fold as correctness F-4. |
| edge-cases | F-3 | First `ingest_unscanned` is suppressed while monotonic is under 30s | CLOSED | spec § Decision 3 lines 77–78. Missing cadence key is `last=0.0`; under 30s with no earlier line is a gap; the host exits 3 if any sample is unavailable; tests patch the plugin module's `time.monotonic` to ≥ 30 (lines 168 and 174). Matches `_log_ingest_unscanned` at `reference_plugin/__init__.py:1356-1358` (`<`, not `<=`). |
| edge-cases | F-4 | Exit 3 leaves a previous report in place | CLOSED | spec § Decision 4 lines 82–83 and § Test plan line 176. Exit 3 does not create or replace `--out`; a pre-seeded file stays byte-for-byte and is not evidence. |
| conventions | F-1 | `_BLOCK_RANK` anchor points at the LOW rank entry | CLOSED | Same fold as correctness F-2. |
| conventions | F-2 | Top-level `observation` is a report-contract addition | CLOSED | spec § Decision 7 lines 117–118. `measurement` is not an alias; `--limit` stays `measurement: "partial"` with `observation: "complete"` when every sample that ran was observed. |
| conventions | F-3 | Exit code 3 is a new CLI contract | CLOSED | spec § Decision 4 lines 82–83. Exit 3 is stated as an addition; exit 2 stays the `--remeasure` refusal; exit 0 stays the write path. |
| conventions | F-4 | Spool restore does not name the autouse fixture it nests under | CLOSED | spec § Decision 2 line 49. Names `tests/conftest.py:_isolate_enforcement_spool` (`:45-69`), the autouse save/restore of path and cap, event tests entering `isolated_observation()` inside the test body, and the harness not passing `cap`. Matches `conftest.py:45-69` and `_reset_events_state` (`petasos/console/_events.py:59-64`), which assigns `SPOOL_CAP_BYTES` only when `cap is not None`. |

No `## Deferred — follow-up required` section. `scale_lens` is off; no scalability report was read. Plane tickets were cached: PET-218 (`30fc3612-cb5e-43f8-b6b0-9cf06ed664a5`, Backlog) and PET-219 (`09461d7c-6ddf-4551-9143-b64fcabc851b`, Backlog). Anchors below were checked with `git show 723cdc5956d024195b3b3afdde09004618266aa6`, not the diverged worktree. Commits since 2026-09-15 that touch the calibrator or changelog (`7bb508a`, `723cdc5`) are inside that base.

## Findings

### F-1: Spool `rule_id` anchor is the severity keyword
**Severity:** P1
**Where:** spec.md:73 | spec § Decision 3
**Claim:** "The spool stores `worst.rule_id` (`reference_plugin/__init__.py:2484`)."
**Why this is wrong:** At `723cdc5`, line 2484 is the severity keyword of that same call. The raw rule id is the next argument:

```2480:2485:docs/deployment/reference_plugin/__init__.py
            _emit_enforcement_event(
                session_id=session_id,
                tool=tool_name,
                event_type="ingest_flagged",
                severity=worst.severity.name,
                rule_id=worst.rule_id,
```

The agreement rule in the same paragraph is right (`shorten_rule_id` of the spool id versus the banner id; both severities are `Severity.name`). The citation points at the wrong field. Neighboring anchors checked at this commit still match, including `formatting.py:70-73` and `:228`, `minimal.py:881`, and the planted phrase hitting only `ignore-previous` among blocking rules.
**Suggested fix:** Cite `rule_id=worst.rule_id` as `:2485`. Keep `:2484` only if the sentence is naming `severity=worst.severity.name`. A range `:2484-2485` is enough for both.

### F-2: `pii_suppressed` counts PII that never blocked
**Severity:** P3
**Where:** spec.md:101 | spec § Decision 6
**Claim:** "`pii_suppressed`: the handler class is `clean` or `ceiling_clean`, at least one finding has `finding_type == "pii"`, and no finding has `finding_type != "pii"` and `ref._blocks(finding.severity)`."
**Why this is wrong:** The plugin withholds a banner only for blocking PII. Non-PII blockers are the banner set; PII is removed from that set (`reference_plugin/__init__.py:2425-2426` and `:2460-2464`). A LOW or MEDIUM `pii` finding never enters `blocking`, so a pii-only result is clean because `_blocks` is false, not because a banner was suppressed. PET-219's problem text is "PII-only HIGH+". The HIGH test still passes, and table A’s base `MinimalScanner` emits no PII, so the published run is unchanged.
**Suggested fix:** Require at least one `finding_type == "pii"` finding for which `ref._blocks(finding.severity)` is true, and keep the existing "no non-pii blocker" guard.

## Summary

P0: 0 | P1: 1 | P2: 0 | P3: 1 | P4: 0

STATUS: RED P0=0 P1=1 P2=0 P3=1 P4=0
