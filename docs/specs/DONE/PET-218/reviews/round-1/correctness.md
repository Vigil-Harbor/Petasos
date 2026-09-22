# Correctness Review — round 1

## Closure of round 0 findings

N/A — round 1

## Findings

### F-1: Flagged spool `rule_id` cannot equal `parse_top_finding`
**Severity:** P0
**Where:** spec.md:68 | spec § Decision 3; spec.md:158 | spec § Test plan; spec.md:188 | spec § Done when
**Claim:** "Exactly one `ingest_flagged`. Its `rule_id` and `severity` equal `parse_top_finding`." The planted HIGH+ pin repeats that the event `rule_id` / `severity` "match `parse_top_finding` and the event." The plugin is left unchanged.
**Why this is wrong:** At `723cdc5`, the banner and the spool row are the same finding, but not the same `rule_id` string. `_emit_enforcement_event` stores the raw id (`docs/deployment/reference_plugin/__init__.py:2480-2485`: `rule_id=worst.rule_id`, `severity=worst.severity.name`). `format_result_notice` prints `shorten_rule_id(finding.rule_id)` (`petasos/session/formatting.py:228`). `shorten_rule_id` strips the prefix `petasos.syntactic.` (`petasos/session/formatting.py:18`, `petasos/session/formatting.py:70-73`). Minimal injection ids are built as `petasos.syntactic.injection.{slug}` (`petasos/scanners/minimal.py:881`). The planted phrase hits `ignore-previous`, so the spool line is `petasos.syntactic.injection.ignore-previous` while `parse_top_finding` (`scripts/pet200_calibrate.py:118`, regex `Top finding: (\S+) \(([A-Z]+)\)`) returns `injection.ignore-previous`. Severity does match (`HIGH` via `.name`). Decision 4 then treats that inequality as an agreement gap, raises `ObservationError`, and `main` exits 3 without a report. Every real HIGH+ sample, including the planted pin and any `run_table_a` that includes one, fail-closes. `rule_histogram` stays on the shortened banner id (Decision 6), so it also cannot equal the raw spool id. The plugin-edit ban makes the spec's equality unsatisfiable, which contradicts the Done when that a HIGH+ sample is a successful matched observation.
**Suggested fix:** Define agreement as: one attributable `ingest_flagged`, no `ingest_unscanned`, `event["severity"] == parse_top_finding severity`, and `shorten_rule_id(event["rule_id"]) == parse_top_finding rule_id`. State that the spool keeps the raw id and the banner/histogram keep the shortened id. Pin the planted sample with both strings (`petasos.syntactic.injection.ignore-previous` on the line, `injection.ignore-previous` from the banner).

### F-2: `_BLOCK_RANK` anchor is the LOW rank entry
**Severity:** P1
**Where:** spec.md:23 | spec § Scope
**Claim:** "`_BLOCK_RANK` (`:376`) ... stay as shipped."
**Why this is wrong:** At `723cdc5`, `docs/deployment/reference_plugin/__init__.py:376` is `Severity.LOW: 3` inside `_SEVERITY_RANK`. `_BLOCK_RANK` is the next assignment, line 379: `_BLOCK_RANK = _SEVERITY_RANK[Severity.HIGH]`. Citing 376 points at the LOW slot (rank 3), not the HIGH gate (rank 1).
**Suggested fix:** Change the anchor to `:379`.

### F-3: `helper_samples` is never defined
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:107 | spec § Decision 7
**Claim:** "`_finalize_cell` writes the three integers when `observation_gaps == 0` and `helper_samples == n`. Otherwise it writes JSON null." Decision 7 also says a null helper cell means the cell was not fully observed and `run_table_a` will not emit that report. The sample loop only says `record_helper` applies Decision 6 or increments `observation_gaps`.
**Why this is wrong:** `helper_samples` is not a field on today's `CellAccum` (`scripts/pet200_calibrate.py:133-162`) and no section says when it increments. `run_table_a` raises only when `observation_gaps > 0` (spec.md:76), then emits the report. If `helper_samples` counts only samples that actually set a helper mark, a clean cell has `helper_samples == 0` and `n > 0`, `_finalize_cell` writes null, and that null report is still returned with `observation: "complete"`. That contradicts "Schema 2 table A stores non-negative integers" and the benign pin that a single observed clean sample finalizes to helper integers 0 (spec.md:159).
**Suggested fix:** Define `helper_samples` as incrementing once per sample whose capture and event agreement succeeded, including a sample whose three marks all stay 0. State that `observation_gaps == 0` after a full cell implies `helper_samples == n`, and that the null branch is only the direct `_finalize_cell` view of a gappy accum the harness will not write.

### F-4: Helper severity tokens are enum names, not `Severity` values
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:93 | spec § Decision 6
**Claim:** "`flagged_medium_plus`: the result contains a finding whose severity is `MEDIUM`, `HIGH`, or `CRITICAL`". The PII guard calls `_blocks(severity)` on that same finding.
**Why this is wrong:** `ScanFinding.severity` is `Severity(enum.Enum)`, not `str` (`petasos/_types.py:31-36`, `petasos/_types.py:52-55`). Member values are lowercase (`"medium"`, `"high"`, `"critical"`). The banner and the spool store `.name` (`HIGH`). `finding.severity in {"MEDIUM", "HIGH", "CRITICAL"}` is always false, and so is a compare against `.value`. `_blocks` keys `_SEVERITY_RANK` by the enum (`docs/deployment/reference_plugin/__init__.py:372-388`); a string severity returns 999 and does not block, which drops the PII-only guard.
**Suggested fix:** Say the check is `finding.severity.name` in `MEDIUM`/`HIGH`/`CRITICAL` (the banner/event spelling), or membership in `{Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL}`, and that `_blocks` is called with `finding.severity`, not `.name` or `.value`.

## Summary

Plane tickets were cached: PET-218 (`30fc3612-cb5e-43f8-b6b0-9cf06ed664a5`, Backlog) and PET-219 (`09461d7c-6ddf-4551-9143-b64fcabc851b`, Backlog). Anchors were checked on `723cdc5956d024195b3b3afdde09004618266aa6`, not the diverged worktree. `origin/master` commits since 2026-09-15 that touch the calibrator or changelog (`7bb508a`, `723cdc5`, and the PET-178/201/204/206/208/209 fixes) are already inside that base. No deferred-findings section is present. The observation lane matches the brief except the flagged `rule_id` gate, which cannot succeed against the shipped banner.

P0: 1 | P1: 1 | P2: 2 | P3: 0 | P4: 0

STATUS: RED P0=1 P1=1 P2=2 P3=0 P4=0
