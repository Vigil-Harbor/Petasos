# Correctness Review — round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | File:line anchors cite the wrong symbols on `723cdc5` | DEFERRED | D-1 (spec.md:221-230) is well-formed. Preamble at spec.md:219 contains `must not implement anything in this section`. Seven fields are present; the suggested-fix blockquote is one `>` line with a single blank line before `Propagation sites`. Sites `§ Scope`, `§ Decision 1`, `§ Design`, and `§ Test plan` all exist. Finding is P1, so the in-scope P0 ceiling does not apply. The same wrong citations are still in the spec (`:40-48` at spec.md:17, `:136` and `:148` at spec.md:19, `:1005` at spec.md:20, `:2426-2433` at spec.md:18, `:668-672` at spec.md:38, `:130-131` at spec.md:83). Not re-filed. |
| edge-cases | F-1 | Floor-copy failure drops the unavailable banner | CLOSED | spec.md:58-60 and the helper snippet at spec.md:109-111 set `head = None` and leave `inspect_failed` false. spec.md:177-178 pins banner rather than `None`. |
| edge-cases | F-2 | Lock-acquire and floor-copy misses are not pinned | CLOSED | spec.md:175-178 pins a raising lock helper (`inspect_failed` false, `head is None`, `cause=boundary`) and a raising `scanner_results` walk (banner, cause not `inspect_error`), outside the six-cause parametrization. |
| edge-cases | F-3 | The inspect exception class is discarded | CLOSED | spec.md:165 forbids the reason from echoing the exception text. spec.md:215 records that the class stays on `errors` and is not copied into the log or reason. |
| edge-cases | F-4 | `with_finding` never shows the sweep matched | CLOSED | spec.md:156-157 requires a real `scan_ingestion_result` call asserting `inspect_failed`, `head is None`, and a blocking finding before the plugin asserts `cause=inspect_error` and no `ingest_flagged`. |
| conventions | F-1 | Unreleased Fixed bullet omits the changelog lead | CLOSED | spec.md:21 and spec.md:141-143 require a prepended `### Fixed` bullet whose first sentence is a bold lead ending in `(PET-205)`, same shape as the PET-211 and PET-209 leads, no em dash, followed by the four claims. |
| conventions | F-2 | Decision 3 chooses two outcomes the brief does not name | CLOSED | spec.md:60 states the operator delta: lock-acquire stays `boundary`; a floor-copy exception also stays `boundary` (`head` cleared) instead of an unannotated pass-through. The old "keep the head" outcome is gone. |
| conventions | F-3 | "Wins over sweep_error" names the wrong rival label | CLOSED | spec.md:72-73 says a raising `inspect()` replaces `boundary`, chunk errors stay on `errors`, and `sweep_error` / `floor_error` stay head-present. spec.md:197 matches. |

## Findings

No findings.

## Summary

Checked at `723cdc5956d024195b3b3afdde09004618266aa6`, not working-tree `38fa604` (`723cdc5` is not an ancestor of HEAD). Plane PET-205 was retrieved (`8953365f-4ecb-4d85-8b31-bc487e9245b9`, Backlog). The last seven days on that base are PET-204, PET-206, PET-209, PET-208, PET-201, PET-200, and PET-211, which the spec already takes as its base. D-1 is the only deferred P0/P1 row; it is well-formed, and the cause split, flag placement, PET-209 order, and real-helper regression still match the brief once those anchors are corrected later. `Pipeline.inspect` still catches `BaseException` and returns empty `scanner_results` (`pipeline.py:672-684` at `723cdc5`); the spec leaves that as `boundary` and drives `inspect_error` only from a raising double.
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
