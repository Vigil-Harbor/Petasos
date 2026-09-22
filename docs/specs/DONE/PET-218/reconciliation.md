# Reconciliation Report: PET-218 / PET-219

> Date: 2026-09-22
> Spec: docs/specs/TODO/PET-218.spec.md
> Merge: PR #190 / `9e9848a8bd2cff1eba9342227ce54b81de3e7acf`
> Plane state: unreachable from this host (last known PET-218 and PET-219 Backlog; group: backlog)
> Close mode: partial-close; Plane was not transitioned

## Summary

PR #190 closes the single PET-218 spec and its PET-219 co-ticket together. It observes the real enforcement-event and helper-result planes in an isolated calibration run, fails closed on incomplete attribution, and publishes schema 2 only when helper columns are measured. All acceptance criteria are met; the committed test artifact records 34 focused tests plus lint and strict typing success. The only drift is the tracked test-output audit artifact beyond the spec's code-file scope.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `scripts/pet200_calibrate.py` | Yes | Adds isolated spool lifecycle, per-sample event attribution, transparent helper capture, split helper metrics, fail-closed gaps, schema 2, and exit 3. |
| `tests/test_pet200_calibration.py` | Yes | Adds the required event/helper, isolation, parser, cadence, cleanup, failure, schema, and regression-fence tests. |
| `CHANGELOG.md` | Yes | Documents real event/helper observation and schema 2 while retaining the schema-1 committed report. |

Unexpected files in diff (not in spec):

- `docs/specs/TODO/PET-218.test-output.txt` — tracked ship-time pytest, lint, and mypy evidence for the close archive.

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | One observation lane closes PET-218 and PET-219 together. | Confirmed | One commit changes the shared sample loop and report row; `scripts/pet200_calibrate.py:442-492` attributes both event and helper observations per sample. |
| 2 | Use a run-scoped real spool and restore all prior state. | Confirmed | `scripts/pet200_calibrate.py:409`; cleanup proof at `tests/test_pet200_calibration.py:855`. |
| 3 | Attribute bounded spool tails by sample identity without letting noise rewrite the handler result. | Confirmed | `scripts/pet200_calibrate.py:356-406`; parser/noise test at `tests/test_pet200_calibration.py:750`. |
| 4 | Fail closed on missing or inconsistent observations. | Confirmed | `ObservationError` at `scripts/pet200_calibrate.py:306`, gap raise at `:947`, and CLI exit 3 at `:1005-1007`. |
| 5 | Transparently wrap the helper; do not stub scanning. | Confirmed | `scripts/pet200_calibrate.py:754-760` saves, awaits, captures, and returns `_observation_scan`. |
| 6 | Keep visible-handler and helper-only metric planes separate. | Confirmed | `scripts/pet200_calibrate.py:191-213`; dedicated MEDIUM, unavailable-with-findings, and PII tests at `tests/test_pet200_calibration.py:627-707`. |
| 7 | Schema 2 means helper columns were measured. | Confirmed | `scripts/pet200_calibrate.py:59-64`, `:788-803`, and `:954-966`; smoke test at `tests/test_pet200_calibration.py:943`. |

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | HIGH+ output and one correlated real `ingest_flagged` event agree on severity and shortened rule id. | Met | `tests/test_pet200_calibration.py:528`. |
| 2 | A clean sample has no findings banner or correlated event. | Met | `tests/test_pet200_calibration.py:558`. |
| 3 | Forced unavailable produces one correlated `ingest_unscanned`. | Met | `tests/test_pet200_calibration.py:596`. |
| 4 | Unavailable-with-findings increments its helper metric without becoming flagged. | Met | `tests/test_pet200_calibration.py:627-649`. |
| 5 | Helper-only MEDIUM increments `flagged_medium_plus` without visible HIGH+ count. | Met | `tests/test_pet200_calibration.py:654-677`. |
| 6 | PII-only blocking findings increment `pii_suppressed` without banner/event. | Met | `tests/test_pet200_calibration.py:682-707`. |
| 7 | Isolation, malformed/duplicate lines, cadence, cleanup, and sentinel preservation are pinned. | Met | `tests/test_pet200_calibration.py:711`, `:750`, `:802`, and `:855`. |
| 8 | Frozen manifest, planted positives, strata, Wilson/policy math, HIGH+ gate, and limited smoke remain green. | Met | Regression tests at `tests/test_pet200_calibration.py:59-425` and schema smoke at `:943`; focused suite passed. |
| 9 | Schema 2 carries measured integer helper fields while the committed PET-200 report remains schema 1. | Met | `scripts/pet200_calibrate.py:59-64`, `:788-803`; test at `tests/test_pet200_calibration.py:943`. The PR did not modify the committed PET-200 report. |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| Planted HIGH+ / real event agreement | Yes | `tests/test_pet200_calibration.py:528` |
| Benign clean observation | Yes | `tests/test_pet200_calibration.py:558` |
| Forced unavailable / findings variant | Yes | `tests/test_pet200_calibration.py:596`, `:627` |
| Helper-only MEDIUM and PII-only | Yes | `tests/test_pet200_calibration.py:654`, `:682` |
| Cross-sample isolation and noisy parser | Yes | `tests/test_pet200_calibration.py:711`, `:750` |
| Cadence suppression reuse | Yes | `tests/test_pet200_calibration.py:802` |
| Exception cleanup and untouched sentinel | Yes | `tests/test_pet200_calibration.py:855` |
| Missing helper fails with exit 3 and preserves output | Yes | `tests/test_pet200_calibration.py:898` |
| Schema-2 limited smoke | Yes | `tests/test_pet200_calibration.py:943` |
| Ship-time commands | Yes | `docs/specs/TODO/PET-218.test-output.txt` — 34 tests passed; ruff and mypy passed. |

## Wiki-ready

Decisions and comprehension worth extracting to the wiki:

- Decision: event evidence corroborates but never overrides the handler return, while helper-only findings populate a separate metric plane.
- Decision: schema 2 asserts complete per-sample observation; missing or inconsistent evidence fails the run rather than coercing unknown values to zero.
- Comprehension: PET-218 and PET-219 jointly add isolated real event capture, transparent helper-result capture, restoration guarantees, and explicit observation completeness to the PET-200 calibration harness.

RECONCILED: yes DRIFT: 1
