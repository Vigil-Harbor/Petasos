The split `try`/`except`/`else`/`finally` matches the helper at `723cdc5`, and the round-1 edge holes are folded. D-1 is a well-formed deferral, so those wrong anchors are not re-filed.

# Edge-Cases Review — round 2

## Closure of round 1 findings
| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | File:line anchors cite the wrong symbols on `723cdc5` | DEFERRED | `### D-1` at spec.md:221-230. Preamble contains `must not implement anything in this section`. Seven fields; suggested-fix blockquote; propagation sites § Scope, § Decision 1, § Design, § Test plan all exist. Finding is P1, so the in-scope-P0 ceiling does not apply. The wrong anchors are still in the spec (spec.md:17 `:40-48`; spec.md:19 `:136` and `:148`; spec.md:20 `:1005`; spec.md:38 `:668-672`; `:130-131` now at spec.md:83). Not re-filed. |
| edge-cases | F-1 | Floor-copy failure drops the unavailable banner | CLOSED | Decision 3 (spec.md:56-60) and the helper snippet (spec.md:109-111) append the error, set `head = None`, and leave `inspect_failed` false. Test plan spec.md:178 requires the unavailable banner rather than `None`. |
| edge-cases | F-2 | Lock-acquire and floor-copy misses are not pinned | CLOSED | spec.md:175-178 pins a raising lock helper (`inspect_failed` false, `head is None`, banner, `cause=boundary`) and a raising `scanner_results` walk, outside the six-cause parametrization. |
| edge-cases | F-3 | The inspect exception class is discarded | DEFERRED | § Deferred (P2+) spec.md:213-215. Class stays on `errors` and is not copied into the log or reason. Deliberate; not a `D-<n>` row. |
| edge-cases | F-4 | `with_finding` never shows the sweep matched | CLOSED | spec.md:155-156: real `scan_ingestion_result` on the same text must show `inspect_failed`, `head is None`, and a blocking finding before the plugin asserts `cause=inspect_error` and no `ingest_flagged`. |
| conventions | F-1 | Unreleased Fixed bullet omits the changelog lead | CLOSED | spec.md:21 and spec.md:141-143: prepended bold lead ending in `(PET-205)`, no em dash. |
| conventions | F-2 | Decision 3 chooses two outcomes the brief does not name | CLOSED | spec.md:60 states the operator delta. Floor-copy now stays `boundary` with `head` cleared; the round-1 "stop clearing head" sentence is obsolete and correctly not copied. |
| conventions | F-3 | "Wins over sweep_error" names the wrong rival label | CLOSED | spec.md:72-73: a raising `inspect()` replaces `boundary`; `sweep_error` stays the head-present, flag-false, nonempty-`errors` case. |

## Findings

No findings.

## Summary
No new persisted record, so the persistence checklist does not apply. Plane PET-205 was retrieved (Backlog, high, `8953365f-4ecb-4d85-8b31-bc487e9245b9`); its `head is None` → `cause=raised` sentence stays the brief's reconciliation, not a new edge. Control flow was checked with `git show 723cdc5956d024195b3b3afdde09004618266aa6`, not working-tree `38fa604` (`723cdc5` is not an ancestor of HEAD). The split `try`/`except`/`else`/`finally` was executed: a lock `Exception` skips `inspect` and leaves the flag false; an `inspect` `Exception` sets the flag and `head = None` and still releases the lock; a floor-copy `Exception` clears `head` and leaves the flag false. `CancelledError` is still not caught, so the PET-206 re-raise and the `wait_for` timeout arm stay `cause=timeout`. At `723cdc5`, `Pipeline.inspect` still catches `BaseException` and returns an empty `scanner_results` result; that shape stays `cause=boundary`, and `inspect_error` is only a propagating raise. That split is Decision 1, and it matches the brief. D-1 is well-formed and was not re-filed.
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
