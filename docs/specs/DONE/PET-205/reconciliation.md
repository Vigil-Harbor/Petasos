# Reconciliation Report: PET-205

> Date: 2026-09-22
> Spec: docs/specs/TODO/PET-205.spec.md
> Merge: PR #189 / `78fa933d382fba17cc114e1cd38abadbb12238f1`
> Plane state: unreachable from this host (last known Backlog; group: backlog)
> Close mode: partial-close; Plane was not transitioned

## Summary

PR #189 implements the real-helper inspect-failure attribution contract without changing the existing timeout, cancellation, cadence, or unavailability precedence. All acceptance criteria are met and the committed verification artifact records 160 focused tests plus lint, format, and strict typing success. The only drift is the expected tracked test-output audit artifact, which was not listed in the spec's production/test scope table.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/session/ingest.py` | Yes | Adds and propagates the typed `inspect_failed` outcome and isolates head-inspect failures from lock/floor-copy failures. |
| `docs/deployment/reference_plugin/__init__.py` | Yes | Classifies the typed outcome as `cause=inspect_error` before the boundary/floor/sweep chain. |
| `tests/test_ingest_scan.py` | Yes | Pins true/false `inspect_failed` outcomes on inspect, chunk, and floor-error paths. |
| `tests/test_reference_plugin_tool_result.py` | Yes | Adds real-helper, HIGH+ precedence, lock-failure, floor-copy, and existing-cause regression coverage. |
| `CHANGELOG.md` | Yes | Adds the PET-205 Unreleased Fixed entry. |

Unexpected files in diff (not in spec):

- `docs/specs/TODO/PET-205.test-output.txt` — tracked ship-time test, lint, format, and mypy evidence for the close archive.

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Use `inspect_error`; preserve `raised` and genuine `boundary`. | Confirmed | `docs/deployment/reference_plugin/__init__.py:2430-2437` checks `inspect_failed` first, then preserves boundary, floor, and sweep classifications; `tests/test_reference_plugin_tool_result.py:714` retains the six existing cause pins. |
| 2 | Carry a typed flag, never parse exception text. | Confirmed | `petasos/session/ingest.py:53` defines `inspect_failed: bool = False`; `:166` sets it only in the head-inspect exception handler. |
| 3 | Lock and floor-copy failures stay `boundary`. | Confirmed | `tests/test_reference_plugin_tool_result.py:783` and `:845` pin both paths as false for `inspect_failed` and not `inspect_error`. |
| 4 | PET-209 unavailability precedence is unchanged. | Confirmed | `tests/test_reference_plugin_tool_result.py:739-780` exercises both benign and HIGH+ payloads and asserts no `ingest_flagged` event. |
| 5 | Transport, cancellation, lock ownership, and budget remain unchanged. | Confirmed | The diff is confined to outcome propagation/classification and tests; no timeout constant, `_run_async`, `_run_ingest_async`, or lock-ownership API changed. |

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | A raising real `pipeline.inspect()` produces the unavailable banner, exact original suffix, one bounded `ingest_unscanned cause=inspect_error`, and no flagged event. | Met | `tests/test_reference_plugin_tool_result.py:739-780`; the committed artifact reports the focused suite passing. |
| 2 | Cause vocabulary remains distinct and is not inferred from exception strings. | Met | `docs/deployment/reference_plugin/__init__.py:2430-2439`; `tests/test_reference_plugin_tool_result.py:714` and `:773`. |
| 3 | Existing `no_pipeline`, `raised`, `timeout`, `boundary`, `floor_error`, and `sweep_error` pins stay green. | Met | `tests/test_reference_plugin_tool_result.py:714`; `docs/specs/TODO/PET-205.test-output.txt` records 160 passing focused tests. |
| 4 | HIGH+ findings do not override inspect unavailability. | Met | Parametrized regression at `tests/test_reference_plugin_tool_result.py:739` asserts unavailable/no flagged for both payload variants. |
| 5 | Ordinary failures remain non-throwing; cancellation, locking, and timeout surface are unchanged. | Met | `tests/test_ingest_scan.py:139-202` pins inspect, chunk, and floor-error behavior; full focused suites passed. |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| Raising inspect through real helper/plugin | Yes | `tests/test_reference_plugin_tool_result.py:739` |
| Existing cause vocabulary | Yes | `tests/test_reference_plugin_tool_result.py:714` |
| Lock-acquire failure remains boundary | Yes | `tests/test_reference_plugin_tool_result.py:783` |
| Floor-copy failure remains boundary | Yes | `tests/test_reference_plugin_tool_result.py:845` |
| Helper inspect/chunk/floor flags | Yes | `tests/test_ingest_scan.py:139`, `:150`, `:187` |
| Sweep/floor unavailability precedence | Yes | `tests/test_reference_plugin_tool_result.py:1148`, `:1193` |
| Ship-time commands | Yes | `docs/specs/TODO/PET-205.test-output.txt` — 160 tests passed; ruff check/format and mypy passed. |

## Wiki-ready

Decisions and comprehension worth extracting to the wiki:

- Decision: `inspect_error` is the typed real-helper failure cause; `raised` remains an outer helper-call failure and `boundary` remains a returned empty/malformed head.
- Comprehension: the ingestion helper now exposes the failure plane explicitly while preserving PET-209's rule that unavailability wins over findings.

RECONCILED: yes DRIFT: 1
