# Conventions Review — round 2

## Closure of round 1 findings
| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | File:line anchors cite the wrong symbols on `723cdc5` | DEFERRED | `## Deferred — follow-up required` D-1 (spec.md:221-230) is well-formed. Preamble at spec.md:219 contains `must not implement anything in this section`. One blockquoted Suggested fix, one blank terminator, seven fields, four propagation sites (`§ Scope`, `§ Decision 1`, `§ Design`, `§ Test plan`) all exist. Scope `in-scope` matches the brief's owned files (`ingest.py`, reference plugin, ingestion tests). `brief: no Scope table` and `brief: no Out-of-scope list` both hold (prose under `## Problem and scope`; no out-of-scope list). P1, so the in-scope P0 ceiling does not apply. The cited anchors are still wrong (`:40-48`, `:136`, `:148`, `:668-672`, `:1005`, `:130-131`, `:2426`). Not re-filed. |
| conventions | F-1 | Unreleased Fixed bullet omits the changelog lead | CLOSED | spec.md:21 and § CHANGELOG spec.md:141-143: prepended `### Fixed` bullet, bold lead ending in `(PET-205)`, no em dash, same shape as the PET-211 / PET-209 leads at `723cdc5` `CHANGELOG.md:112` and `:134`. |
| conventions | F-2 | Decision 3 chooses two outcomes the brief does not name | CLOSED | spec.md:54-60 now states the operator delta. Both paths stay today's `boundary`. The round-1 "stop clearing `head`" sentence was superseded by the edge-cases fold, not left undone. |
| conventions | F-3 | "Wins over sweep_error" names the wrong rival label | CLOSED | spec.md:71-73: a raising `inspect()` replaces `boundary`; `sweep_error` stays head-present and flag-false. Done when spec.md:197 says the same. |
| edge-cases | F-1 | Floor-copy failure drops the unavailable banner | CLOSED | spec.md:57-58 and the helper snippet spec.md:109-111 set `head = None` and leave `inspect_failed` false. Pin at spec.md:178: banner, not `None`. |
| edge-cases | F-2 | Lock-acquire and floor-copy misses are not pinned | CLOSED | spec.md:175-178 pins a raising lock helper as `cause=boundary` and a raising `scanner_results` walk as unavailable, outside the six-cause parametrization. |
| edge-cases | F-3 | The inspect exception class is discarded | DEFERRED | spec.md:213-215 (`## Deferred (P2+)`). P3, so no D-row. Decision 2 still forbids choosing `cause` from the exception string; the class stays on `errors` and out of `reason` (spec.md:165). Deliberate, not a revert. |
| edge-cases | F-4 | `with_finding` never shows the sweep matched | CLOSED | spec.md:156: the real helper must show `inspect_failed`, `head is None`, and a HIGH-or-worse finding before the plugin asserts `inspect_error` and no `ingest_flagged`. |

## Findings

No findings.

Checked at `723cdc5956d024195b3b3afdde09004618266aa6`, not working-tree `38fa604`. Decision 1 is brief contract item 2. Decision 2 matches the plugin's existing `getattr(scan, "head", None)` read (`reference_plugin/__init__.py:2418`) and does not add a registry or a removal shim. Decision 3 now preserves today's `boundary` labels rather than a new outcome. Decision 4 keeps the active PET-209 precedence (`decisions/2026-09-20-pet-209-incomplete-coverage-precedence.md`) and the PET-170 annotate-not-withhold return. PET-178's layered head, ingest loop, and mutex stay untouched. `inspect_error` / `inspect_failed` are unused names on that commit. The changelog bullet is a `### Fixed` prepend. `mypy --strict` only on `ingest.py` matches `pyproject.toml` `ignore_errors` for `reference_plugin` and the PET-211 command shape. Plane PET-205 (`8953365f-4ecb-4d85-8b31-bc487e9245b9`, Backlog) still says `head is None` → `cause=raised`; Decision 1 records that as the post-ship wording replacement and does not treat it as the implementation contract.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
