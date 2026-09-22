# PET-205 — Real-helper inspect failures emit `inspect_error`

Base: `origin/master` `723cdc5956d024195b3b3afdde09004618266aa6` (PR #188). Ship-spec cuts the worktree from `origin/master`. Local `master` at `38fa604` is two archive commits ahead of the pre-PET-204 divergence and seven commits behind `origin/master`. It does not contain PET-204, PET-206, PET-209, PET-208, PET-201, PET-200, or PET-211. Every file:line anchor below is `723cdc5`. Verify code claims with `git show 723cdc5:<path>`, not the working tree.

Authority: `docs/specs/TODO/PET-205.brief.md`. Plane PET-205 (`8953365f-4ecb-4d85-8b31-bc487e9245b9`, Backlog, high) is the 2026-09-16 parent text. Its suggested remediation still maps `scan.head is None` to `cause=raised`. That sentence is stale against the landed helper. This spec is the reconciliation the brief requires. The Plane description is not the implementation contract.

Preflight: `upstream: skipped (no remote)`; `origin: behind-7 (diverged — proceeded)`; `scale-lens: off`. No `## Scale` section in the brief.

## Goal

When `pipeline.inspect()` raises inside the real `scan_ingestion_result()`, the reference plugin already returns the scan-unavailable banner, keeps the original tool result, and emits one `ingest_unscanned` event. It labels that event `cause=boundary`. `cause=raised` is pinned only by replacing `scan_ingestion_result` with a raising stub. This change makes the real-helper inspect failure its own stable cause, `inspect_error`, and leaves genuine empty-floor `boundary`, helper-stub `raised`, `timeout`, `no_pipeline`, `floor_error`, and `sweep_error` on their current pins. PET-209 still reports unavailability before findings.

## Scope

| File | Region / action |
|---|---|
| `petasos/session/ingest.py` | Add `inspect_failed: bool = False` on `IngestionScanResult` (`:40-48`). Set it only when `_inspect_head()` (`:141-148`) raises `Exception`. Split that call out of the shared `try` at `:150-165` so a lock-acquire failure and a post-return floor-error copy do not set the flag. A floor-copy exception clears `head` and leaves the flag false, which keeps today's unavailable banner. Pass the flag on all three `IngestionScanResult(...)` returns (`:177`, `:208`, `:216`). |
| `docs/deployment/reference_plugin/__init__.py` | In `_transform_tool_result`, when `cause` is still `None` (`:2426-2433`), read `scan.inspect_failed` and assign `cause = "inspect_error"` before the `boundary` / `floor_error` / `sweep_error` chain. Update the PET-205 comment at `:2413-2418`. Do not edit `_ingest_one` (`:527-551`), the banner call, or the event f-string shape. |
| `tests/test_ingest_scan.py` | Extend `test_helper_never_raises_on_a_raising_inspect` (`:136`) to assert `inspect_failed is True`. Assert `inspect_failed is False` on the existing floor-error helper test (`:185`) and the existing chunk-failure helper test (`:148`). |
| `tests/test_reference_plugin_tool_result.py` | Add one parametrized regression beside `_drive_unavailable` (`:652`). Do not edit the six-cause parametrization (`:699-704`) or the PET-209 sweep/floor tests (`:1005`, `:1052`). |
| `CHANGELOG.md` | Prepend one Unreleased `### Fixed` bullet. First sentence is a bold lead ending in `(PET-205)`. No em dash. |

**Left alone:**

- `petasos/pipeline.py`. `inspect()` stays never-throwing for a real `Pipeline`. The regression drives a raising test double through the real helper.
- `petasos/__init__.py` and `petasos/session/__init__.py`. `IngestionScanResult` is already exported. No new name.
- `_run_ingest_async`, `_run_async`, `_acquire_inspect_lock`, `_inspect_lock` ownership, and `_result_scan_timeout`.
- The six `_drive_unavailable` arms and their cause strings.
- Banner copy (`format_result_notice("scan_unavailable", ...)`), cadence clocks, and the `ingest_unscanned` reason prefix.
- Calibration harness, thresholds, release, Hermes deployment, and the wiki checkout.

## Decisions

### Decision 1 — `inspect_error`, not `raised`, and not a pinned `boundary`

The brief's contract item 2 is the reconciliation. Two options were open. This spec takes the second.

`cause=boundary` stays the genuine malformed-head category: `scan` returned, `inspect_failed` is false, and `head` is missing, `head.scanner_results` is empty, or the `minimal` floor is absent. That is what `_drive_unavailable(..., "boundary")` builds today (`:668-672`): a `PipelineResult` with `scanner_results=()`. A raising `inspect()` is not that result.

`cause=raised` stays the outer failure: `_run_ingest_async` / the helper callable itself raises. `_drive_unavailable(..., "raised")` (`:657-661`) replaces `scan_ingestion_result` with a raising stub. Mapping the real-helper path onto `raised` would make those two operator events the same token and would fail contract item 3.

The 2026-09-16 Plane remediation (head is `None` or `scan.errors` from a raising inspect → `cause=raised`) is not implemented. It collapses `raised` with the real helper, and it would also treat every nonempty `errors` tuple as `raised`, including `floor_error` and `sweep_error`. Contract item 3 forbids that collapse.

The operator-facing Plane wording to replace, after ship, is that remediation paragraph. Replacement: a real-helper inspect exception sets `IngestionScanResult.inspect_failed` and the plugin emits `cause=inspect_error`; `cause=raised` stays the helper-callable failure; an empty `scanner_results` result stays `cause=boundary`. Editing Plane is not an implementation task.

### Decision 2 — The flag is the cause. Exception text is not.

`scan_ingestion_result` still appends `f"{type(exc).__name__}: {exc}"` to `errors`. That string is diagnostic. The plugin must not read it, substring-match it, or otherwise infer the cause from it.

The typed outcome is `IngestionScanResult.inspect_failed: bool = False`. Default `False` keeps the four-argument constructors source-compatible. The plugin reads it with `getattr(scan, "inspect_failed", False)` so a non-dataclass double does not throw. Missing or false falls through to the existing chain.

Only `_inspect_head()` raising `Exception` sets the flag, and that same handler sets `head = None`. `CancelledError` is a `BaseException` and is not caught. The PET-206 `task.cancelling()` check (`:170-172`) and the `head.errors` `CancelledError` return (`:173-182`) stay as they are, with `inspect_failed` false unless the flag was already set.

### Decision 3 — Lock failure and a floor-copy exception stay `boundary`

A lock-acquire `Exception` is caught, recorded, and does not set `inspect_failed`. `head` stays `None`. The sweep still runs. The plugin classifies that as `boundary`, which is today's label. This spec does not add a lock cause.

Copying `minimal` floor errors (`:155-159`) moves into an `else` of the inspect call. If that copy raises, append the error, set `head = None`, and leave `inspect_failed` false. Do not keep that head. The plugin walks `scanner_results` again with no guard (`:2418-2423`). An exception there is not a scan cause: the outer handler at `:2526` logs `PETASOS_RESULT_SCAN_ERROR` and returns `None`, so the tool text is passed through with no banner. Clearing `head` makes the plugin take `boundary` and return the unavailable banner, which is what the single `try` does today.

Operator delta: a lock-acquire failure stays today's `boundary`. A floor-copy exception also stays `boundary` (`head` cleared, flag false) instead of escaping the plugin as an unannotated pass-through. Neither path is `inspect_error`.

### Decision 4 — PET-209 order is unchanged

`decisions/2026-09-20-pet-209-incomplete-coverage-precedence.md` stays in force. Any assigned `cause` returns the scan-unavailable banner and can emit `ingest_unscanned`. It does not emit `ingest_flagged`. Findings stay on the helper result. The plugin does not consult them once `cause` is set.

Predicate order when `cause` is still `None`:

1. `scan is not None` and `inspect_failed` → `inspect_error`
2. `scan is None` or `head is None` or empty `scanner_results` or no `minimal` floor → `boundary`
3. `floor.error is not None` → `floor_error`
4. `scan.errors` nonempty → `sweep_error`

A raising `inspect()` clears `head`, so the cause it replaces is `boundary`. A later chunk error remains on `errors` and does not change that cause. `sweep_error` stays the head-present, flag-false, nonempty-`errors` case. `floor_error` stays the head-present floor-`error` case. One event carries one cause. Do not retune the HIGH+ versus `sweep_error` rule. That rule already shipped as PET-209.

### Decision 5 — No transport or budget change

The helper remains cancellation-correct and returns on ordinary scan failures. Do not move the scan onto `_run_async`. Do not change who acquires or releases `_inspect_lock`. Do not change `_result_scan_timeout`, the `wait_for` in `_ingest_one`, or the timeout margin. `cause=timeout` stays the `TimeoutError` arm at `:2409-2410`.

## Design

### Helper

Initialize `inspect_failed = False` next to `head: PipelineResult | None = None` (`:130-131`) so the outer handler can read it.

Replace the single `try` at `:150-165` with this shape. The `finally` still releases only when `acquired` is true, and it still runs before the PET-206 cancellation check.

```python
acquired = False
try:
    if inspect_lock is not None:
        await _acquire_inspect_lock(inspect_lock)
        acquired = True
except Exception as exc:
    errors.append(f"{type(exc).__name__}: {exc}")
else:
    try:
        head = await _inspect_head()
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        head = None
        inspect_failed = True
    else:
        try:
            errors.extend(
                result.error
                for result in head.scanner_results
                if result.scanner_name == "minimal" and result.error is not None
            )
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            head = None
finally:
    if acquired and inspect_lock is not None:
        inspect_lock.release()
```

Pass `inspect_failed=inspect_failed` on the cancellation return, the success return, and the outer `except Exception` return. The outer handler still drops findings and returns `coverage` with `chunk_count=0`. It must not clear the flag.

`IngestionScanResult`'s docstring states that nonempty `errors` invalidate a complete-coverage claim, and that `inspect_failed` means the head `inspect()` call raised. Hosts must not report that flag as `boundary`.

### Plugin

After `floor` is resolved and before the existing `if cause is None` body, branch on the flag first:

```python
if cause is None:
    if scan is not None and getattr(scan, "inspect_failed", False):
        cause = "inspect_error"
    elif scan is None or head is None or not head.scanner_results or floor is None:
        cause = "boundary"
    elif floor.error is not None:
        cause = "floor_error"
    elif scan.errors:
        cause = "sweep_error"
```

The comment above that block names `inspect_error` as the real-helper inspect failure. It no longer says a raising inspect is left as PET-205 follow-up inside `boundary`.

The unavailable return is unchanged: `format_result_notice("scan_unavailable", tool_name) + "\n\n" + result`. The event, when the cadence helper logs, stays `event_type="ingest_unscanned"` and `reason=f"{_RESULT_SCAN_ERROR_REASON} cause={cause} len={len(result)}"`. No second event. No `ingest_flagged` on this path.

### CHANGELOG

Prepend under `## [Unreleased]` / `### Fixed` (do not append after older bullets). The first sentence is a bold lead ending in `(PET-205)`, in the same shape as the PET-211 and PET-209 leads. No em dash. The rest of the bullet states: a raising `inspect()` through `scan_ingestion_result` sets `IngestionScanResult.inspect_failed` and the reference plugin emits `ingest_unscanned` `cause=inspect_error`. Empty `scanner_results` stays `cause=boundary`. `cause=raised` stays the helper-callable failure. Unavailability still wins when the sweep also has a HIGH+ finding.

## Test plan

Helper, in `tests/test_ingest_scan.py`:

- `test_helper_never_raises_on_a_raising_inspect`: still no raise, `head is None`, `errors` nonempty, and `inspect_failed is True`.
- `test_head_floor_error_is_recorded_even_when_sweep_finds_injection`: `inspect_failed is False`, `head is not None`, findings still present, floor text still in `errors`.
- `test_failed_chunk_scan_is_recorded_and_does_not_raise`: `inspect_failed is False`.

Plugin regression, new, in `tests/test_reference_plugin_tool_result.py`. Parametrize `with_finding: bool`. Do not monkeypatch `scan_ingestion_result`. Install a pipeline double whose `inspect` raises `RuntimeError`, the same shape as `_Boom` in the helper test, on the real `_transform_tool_result` path.

- `with_finding` false: result text is benign.
- `with_finding` true: result text contains the module's existing `_INJECTION`. Before the plugin assertion, call the real `scan_ingestion_result` on that same text and assert `inspect_failed is True`, `head is None`, and at least one finding whose severity blocks (HIGH or worse). Then assert the plugin emits `cause=inspect_error` and no `ingest_flagged`. An empty flagged list alone does not prove the sweep matched.

Both arms:

- Return value is a `str`, contains `could not scan the content below`, and `endswith` the exact original result.
- The notice prefix has no `Scanned` count and no `Coverage:` line.
- `_events("ingest_unscanned")` has length 1. `reason` contains `cause=inspect_error` and `len=<exact length>`, starts with `result scan unavailable`, and is at most 200 characters.
- `rule_id` and `severity` on that row are `None`.
- `_events("ingest_flagged")` is empty.
- The reason does not echo the exception text. `RuntimeError` is not required in the reason.

Pins that must stay green without changed expectations:

- `test_every_unscannable_cause_annotates_with_a_distinguishable_token` for `no_pipeline`, `raised`, `timeout`, `boundary`, `floor_error`, `sweep_error`.
- `test_sweep_error_with_high_findings_does_not_claim_full_coverage` and `test_head_floor_error_with_sweep_findings_reports_unavailable`.
- `test_lone_surrogate_in_second_chunk_reports_unavailable`.
- Cadence tests (`test_ingest_unscanned_cadence_second_call_keeps_banner` and the host-session clock test).
- Cancellation, loop-isolation, lock/reconfigure, and ceiling tests in `tests/test_ingest_scan.py` and `tests/test_reference_plugin_tool_result.py`.

Two pins for the split `try`, outside the six-cause parametrization:

- A lock helper that raises `RuntimeError` before `inspect`: `inspect_failed is False`, `head is None`, the banner is present, and one `ingest_unscanned` reason contains `cause=boundary`.
- A returned head whose `scanner_results` iteration raises: `inspect_failed is False`, the plugin return is the unavailable banner rather than `None`, and the cause is not `inspect_error`.

The regression class is: a raising `inspect` observed only through a stubbed helper, so the real helper's `head is None` result was labeled `boundary`.

## Test command

```
C:\Python314\python.exe -m pytest tests/test_ingest_scan.py tests/test_reference_plugin_tool_result.py -q --tb=short
C:\Python314\python.exe -m ruff check petasos/session/ingest.py docs/deployment/reference_plugin/__init__.py tests/test_ingest_scan.py tests/test_reference_plugin_tool_result.py
C:\Python314\python.exe -m ruff format --check petasos/session/ingest.py docs/deployment/reference_plugin/__init__.py tests/test_ingest_scan.py tests/test_reference_plugin_tool_result.py
C:\Python314\python.exe -m mypy --strict petasos/session/ingest.py
```

`pyproject.toml` sets `ignore_errors` for the `reference_plugin` module. Plugin type safety for this change is the pytest pin plus ruff on that file. Do not treat a clean `mypy` of `ingest.py` as a typecheck of the plugin.

## Done when

- A regression drives a raising `pipeline.inspect()` through the real `scan_ingestion_result()` and the real `_transform_tool_result()`. The return contains the scan-unavailable annotation, the original content is the exact suffix, and one bounded `ingest_unscanned` reason is emitted with `cause=inspect_error`. There is no silent pass-through and no `ingest_flagged` event.
- The cause vocabulary is reconciled as Decision 1. `boundary` remains the empty or floor-absent head. `inspect_error` is the real-helper inspect exception. Cause is not inferred from exception strings.
- `no_pipeline`, outer/helper `raised`, `timeout`, genuine `boundary`, `floor_error`, and `sweep_error` stay distinct. Their existing pins stay green. A raising `inspect` is not reported as `boundary`. A head-present `floor_error` or `sweep_error` is not reported as `inspect_error`.
- The same raising-inspect case with a syntactic HIGH+ finding elsewhere in the payload still reports unavailable and does not emit `ingest_flagged`.
- The helper still does not raise on ordinary scan failures. Cancellation, lock ownership, and the timeout surface are unchanged. The scan is not moved back onto `_run_async`.

## Out of scope

- Reviving the 2026-09-16 five-cause rewrite, including mapping `head is None` or any `scan.errors` entry onto `cause=raised`.
- Parsing exception strings to choose a cause.
- A new cause for lock-acquire failure. That path stays `boundary`.
- Retuning PET-209. Unavailability already wins before findings.
- Dropping sweep findings from `IngestionScanResult` when inspect fails.
- Changing banner wording, event cadence, `_MAX_REASON_LEN`, scan budget, chunk sizes, or ceiling accounting.
- Moving the scan onto `_run_async`, changing lock ownership, or widening the timeout surface.
- Calibration-harness work, threshold changes, a package release, or a Hermes deployment.
- Editing the wiki, or editing the Plane description as part of the code change. Decision 1 records the replacement sentence for the operator.

## Deferred (P2+)

- edge-cases/R1/F-3 (P3): the inspect exception class stays on `IngestionScanResult.errors` and is not copied into the `ingest_unscanned` log or reason. Decision 2 forbids choosing `cause` from that string. A separate class token in the log is not part of this spec.

## Deferred — follow-up required

> Known, unfixed P0/P1 findings. Not part of this spec's implementation: `/ship-spec` must not implement anything in this section. Each row becomes a follow-up ticket filed by the operator.

### D-1: File:line anchors cite the wrong symbols on `723cdc5`
**Finding:** correctness/R1/F-1 (P1)
**Deferred in:** round 1
**Where:** spec § Scope, spec.md:17; spec.md:19; spec.md:20; spec.md:38; spec.md:81
**Suggested fix:**
> Retarget the citations to the lines in the table, and state that `inspect_failed: bool = False` is appended after `errors` (line 50). Point the boundary sentence at 673-679 / the constructor at 678, not the timeout wedge. Point the sweep-test "do not edit" cite at 1007. Point the `cause is None` chain at 2427-2433.

**Propagation sites:** § Scope; § Decision 1; § Design; § Test plan
**Scope:** in-scope — spec anchors for `petasos/session/ingest.py`, `docs/deployment/reference_plugin/__init__.py`, and the ingestion tests; brief: no Scope table; brief: no Out-of-scope list
**Follow-up:** PET-220
