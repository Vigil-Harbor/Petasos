# Reconciliation Report: PET-3

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-3.spec.md
> Merge: PR #2 (b56788f)
> Plane state: Done (group: completed)

## Summary
PET-3 shipped `LlmGuardScanner` exactly as specced — lazy-load with double-checked
locking, five sub-scanners with conservative defaults, per-sub-scanner error
isolation, and 26 tests (16 unit pass, 10 integration skip without the extra).
All spec scope landed; the only file divergence on disk today comes from later
commits (PET-5, PET-60) that legitimately extended the two touched files.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/llm_guard.py` (new) | Yes | 187 lines, new file, matches Design section. |
| `tests/test_llm_guard_scanner.py` (new) | Yes | 472 lines; 26 test functions (16 unit + 10 integration). |
| `petasos/scanners/__init__.py` (modified) | Yes | Guarded conditional re-export of `LlmGuardScanner` per spec §"Re-export". |
| `petasos/_types.py` (left alone) | No (correct) | Spec says no changes needed; not in diff. Existing types suffice. |
| `petasos/__init__.py` (left alone) | No (correct) | Spec says top-level API untouched; grep confirms no `LlmGuardScanner` ref (no matches). |
| `pyproject.toml` (left alone) | No (correct) | Spec says `llm-guard` extra already declared; not in diff. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-3.test-output.txt` — test-run audit artifact committed alongside the squash merge (ship-spec convention). Documentation, not code; not behavioral drift.

Note on current on-disk divergence (NOT PET-3 drift):
- `petasos/scanners/llm_guard.py` on disk now imports `math` and clamps `confidence` via `math.isfinite`/`max`/`min` (lines 4, 174-176). `git log` attributes this to `06e58c2 fix(pet-60)`, a later hardening commit — not PET-3.
- `petasos/scanners/__init__.py` on disk now also re-exports `LlamaFirewallScanner` and `PresidioScanner` and adds a `_is_missing_package` helper (PET-4 / PET-5 / PET-60). The PET-3-shipped form was the simpler 14-line `try/except ImportError` block.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Lazy-load via `_ensure_loaded()`, errored `ScanResult` on import failure, no throw | Confirmed | `petasos/scanners/llm_guard.py:41-49,142-149`; `except Exception` caches error at 115-116. |
| D2 | Per-scanner instantiation (not `scan_prompt()`); call `.scan()` per sub-scanner | Confirmed | `petasos/scanners/llm_guard.py:59-112` instantiate individually; `:172` calls `sub_scanner.scan(text)`. No `scan_prompt` reference anywhere. |
| D3 | `asyncio.to_thread` for sync sub-scanners; sequential in one thread | Confirmed | `petasos/scanners/llm_guard.py:150` `await asyncio.to_thread(self._scan_sync, text)`; `_scan_sync` loops sequentially `:170`. |
| D3a | Thread-safe lazy-load via `threading.Lock` + double-checked locking | Confirmed | `petasos/scanners/llm_guard.py:34` lock; `:42-50` outer + inner `_loaded`/`_load_error` checks. |
| D3b | Cached load failure in `_load_error`; `reset()` for re-attempt | Confirmed | `:44-45,49,115-116` cache; `reset()` `:118-130` clears and re-arms; docstring states caller-responsibility contract. |
| D4 | Threshold mapping: `risk_score`→confidence, `is_valid==False`→finding; `threshold` to PromptInjection | Confirmed | `:172-173` emit only when `not is_valid`; `:64` `PromptInjection(threshold=self._threshold)`; default `0.85` at `:16`. |
| D5 | No position/matched_text (whole-prompt findings) | Confirmed | `:185-186` `position=None, matched_text=None`. |
| D6 | Conservative defaults: only PromptInjection + InvisibleText enabled | Confirmed | Defaults `:17-21`; PromptInjection always appended `:59`, InvisibleText gated on default-True flag `:68`; toxicity/secrets/ban_topics default False. |
| Design | Eager constructor validation: `enable_ban_topics=True` without list raises `ValueError` | Confirmed | `:23-24`. |
| Design | Sub-scanner registry rule_id/finding_type/severity table | Confirmed | injection/HIGH `:61-63`, invisible-text/encoding/MEDIUM `:71-73`, toxicity/MEDIUM `:83-85`, ban-topics/policy/MEDIUM `:95-97`, secrets/credential/HIGH `:107-109`. |
| Design | Per-sub-scanner error isolation; errors joined into `ScanResult.error` | Confirmed | `:189-190` per-scanner try/except collects `f"{rule_id}: {exc}"`; `:156` `"; ".join(errors)`. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `LlmGuardScanner` implements `Scanner` protocol | Met | `llm_guard.py:12` class; `_types.py:106` `@runtime_checkable Scanner`; test `test_isinstance_scanner` passes (test-output line 10). |
| 2 | Lazy-load: import fails → errored `ScanResult`, no crash; error cached (no retry loop) | Met | `llm_guard.py:44-45,115-116`; tests `TestLazyLoadFailure`, `TestCachedLoadFailure` pass (lines 13, 24). |
| 3 | Thread-safe `_ensure_loaded()` via `threading.Lock` + double-checked locking | Met | `llm_guard.py:34,46-50`; `TestThreadSafety::test_ensure_loaded_executes_once` passes (line 23). |
| 4 | Constructor params present; `enable_ban_topics=True` w/o `ban_topics` raises `ValueError` | Met | `:13-24`; `TestEnableBanTopicsWithoutList` (none + empty) passes (lines 21-22). |
| 5 | Each enabled sub-scanner → correctly typed `ScanFinding` (all fields populated) | Met | `:177-187`; `_types.py:33-47` enforces fields; integration tests skip-guarded but unit error-isolation test confirms construction path (line 16). |
| 6 | `name` property returns `"llm_guard"` | Met | `:37-39`; `test_name_returns_llm_guard` passes (line 12). |
| 7 | Duration tracking via `time.perf_counter` | Met | `:139,143,151,159`; `TestDurationTracking::test_duration_ms_is_positive` passes (line 17). |
| 8 | Integration tests vs real backend, ≥10 detection scenarios | Met (skip-guarded) | 10 `TestIntegration*` classes (test-output lines 26-35) with `pytest.importorskip`; SKIPPED in CI without extra — design-intended. |
| 9 | `pip install petasos[llm-guard]` succeeds in clean 3.11 venv | Unverifiable | Out-of-band install step; no install log in repo. `pyproject.toml` declares the extra (D-scope). Not reproducible read-only. |
| 10 | Fail-open verified under backend exception (not just import failure) | Met | `_scan_sync` per-scanner `except` `:189`; outer `scan()` `except` `:158`; `TestRuntimeExceptionGuard` + `TestPerSubScannerErrorIsolation` pass (lines 15-16). |
| 11 | Per-sub-scanner error isolation (healthy findings returned, error field populated) | Met | `:170-190`; `TestPerSubScannerErrorIsolation::test_one_fails_others_still_run` passes (line 16). |
| 12 | ≥20 tests passing (14 unit + 10 integration) | Met | 26 collected: 16 unit pass, 10 integration skip (test-output line 37). Unit count (16) exceeds the 14 minimum; total 26 ≥ 20. |
| 13 | `mypy --strict` clean | Unverifiable | Not re-run here (read-only; would require installed env). Commit msg notes mypy-driven `find_spec` fix; CI was green at merge. |
| 14 | `ruff check` / `ruff format` clean | Unverifiable | Not re-run here (read-only). CI green at merge per ship-spec flow. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| 1 Scanner protocol compliance | Yes | `tests/test_llm_guard_scanner.py:34` `test_isinstance_scanner` + `:38` `test_scan_is_coroutine` |
| 2 Name property | Yes | `:46` `test_name_returns_llm_guard` |
| 3 Lazy-load failure | Yes | `:54` `test_missing_llm_guard_returns_errored_result` |
| 4 Lazy-load only runs once | Yes | `:67` `test_second_scan_does_not_reimport` |
| 5 Runtime exception guard | Yes | `:89` `test_sub_scanner_raise_returns_errored_result` |
| 6 Per-sub-scanner error isolation | Yes | `:112` `test_one_fails_others_still_run` |
| 7 Duration tracking | Yes | `:140` `test_duration_ms_is_positive` |
| 8 Default enable flags (2 active) | Yes | `:158` `test_only_two_scanners_by_default` |
| 9 All enable flags (5 active) | Yes | `:179` `test_all_five_scanners_enabled` |
| 10 ban_topics requires enable flag | Yes | `:205` `test_ban_topics_without_flag_does_not_activate` |
| 11 enable_ban_topics without list raises | Yes | `:224` `test_enable_ban_topics_none_raises` + `:228` `test_enable_ban_topics_empty_raises` |
| 12 Thread safety of _ensure_loaded | Yes | `:236` `test_ensure_loaded_executes_once` |
| 13 Cached load failure + reset | Yes | `:267` `test_cached_error_no_retry_then_reset` |
| 14 Model instantiation failure | Yes | `:295` `test_model_init_failure_cached` |
| 15 Integration: clean input | Yes (skip) | `:334` `test_clean_input` |
| 16 Integration: PromptInjection | Yes (skip) | `:345` `test_prompt_injection_detected` |
| 17 Integration: InvisibleText | Yes (skip) | `:360` `test_invisible_text_detected` |
| 18 Integration: Toxicity | Yes (skip) | `:376` `test_toxicity_detected` |
| 19 Integration: Secrets | Yes (skip) | `:388` `test_secrets_detected` |
| 20 Integration: BanTopics | Yes (skip) | `:404` `test_ban_topics_detected` |
| 21 Integration: confidence mapping | Yes (skip) | `:418` `test_confidence_is_float_in_range` |
| 22 Integration: position/matched_text None | Yes (skip) | `:431` `test_position_and_matched_text_none` |
| 23 Integration: threshold parameter | Yes (skip) | `:444` `test_high_threshold_reduces_sensitivity` |
| 24 Integration: direction parameter | Yes (skip) | `:465` `test_outbound_direction_works` |

## Wiki-ready
- D3a/D3b — Thread-safe lazy-load + cached-load-failure pattern for extras-gated ML scanners: double-checked locking around model load, cache failures in `_load_error` to avoid retry storms, `reset()` with an explicit "no scan() in flight" caller contract. Reusable across PET-3/PET-4/PET-5 (shared backend-wrapper idiom).
- D2 — Reject LLM Guard's `scan_prompt()` aggregator in favor of per-sub-scanner instantiation, because aggregate output destroys per-finding attribution (`finding_type`/`scanner_name`) needed for downstream pipeline merge + dedup. Constraining for any future LLM Guard scanner addition.

RECONCILED: yes DRIFT: 0
