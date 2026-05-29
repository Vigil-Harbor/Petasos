# Reconciliation Report: PET-6

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-6.spec.md
> Merge: PR #5 (9e68599)
> Plane state: Done (group: completed)

## Summary
PET-6 shipped the `Pipeline` orchestrator and `PetasosConfig` dataclass exactly as specified — 12-stage `inspect()`, running-winner finding merge, three fail-modes, defensive config copy, and four no-op premium hooks, with 72 passing tests (spec floor 60). All decisions confirmed against the shipped commit; the only drift is a CI test-output artifact committed alongside the named scope files.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/config.py` (new) | Yes | 75 lines added; frozen dataclass, validation, `to_dict`/`from_dict`/`copy` per §4.1. (Now 377 lines on disk — grown by PET-7..10.) |
| `petasos/pipeline.py` (new) | Yes | 324 lines added; `Pipeline`, `merge_findings`, `_compute_safe`, `_scan_one`, 4 hooks per §4.2-4.6. |
| `tests/test_pipeline.py` (new) | Yes | 46 test fns (spec floor 40). |
| `tests/test_config.py` (new) | Yes | 15 test fns (spec floor 10). |
| `tests/test_finding_merge.py` (new) | Yes | 12 test fns (spec floor 10). |
| `petasos/__init__.py` (modify) | Yes | Exports `Pipeline`, `PetasosConfig` added. |
| `petasos/_types.py` (no change expected) | No (unchanged) | Confirmed not in diff — `PipelineResult` reused as-is, matching spec. |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-6.test-output.txt` (+85) — CI audit artifact (pytest/mypy/ruff output) from the ship-spec process; not a named scope file but expected by workflow convention, not a code change.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | `asyncio.gather` + per-scanner `Exception` wrap (not `TaskGroup`/`BaseException`) | Confirmed | Shipped `_scan_one` `except Exception as exc` (9e68599:petasos/pipeline.py); fan-out via `asyncio.gather(*tasks)` in stage 4. (Current disk pipeline.py:164/426 now uses `BaseException`+`return_exceptions=True` from a later ticket — outside PET-6 scope.) |
| D2 | MinimalScanner first, synchronously, before fan-out + closed-mode early exit | Confirmed | Stage 2 awaits `self._minimal_scanner.scan(text,...)` on raw text; stage 3 sets `early_exit` on CRITICAL in closed mode (9e68599:petasos/pipeline.py). Current: pipeline.py:406, :413. |
| D3 | Fail-mode defaults to `degraded` | Confirmed | `fail_mode: Literal[...] = "degraded"` config.py:56. |
| D4 | Premium hooks = no-op methods, not middleware | Confirmed | Four `async def _premium_*_hook(...) -> None: pass` shipped (9e68599:petasos/pipeline.py). |
| D5 | `PetasosConfig` standalone dataclass, not Drawbridge subclass | Confirmed | `@dataclass(frozen=True) class PetasosConfig` config.py:43, no base class. |
| D6 | Constructor takes defensive `copy.deepcopy` of config | Confirmed (shipped) | Shipped: `self._config = copy.deepcopy(config) ...` (9e68599:petasos/pipeline.py). Drifted on disk: current pipeline.py:199 uses `replace(config)` (later-ticket change); test `test_config_defensive_copy` (test_pipeline.py:119) still guards the invariant. |
| D7 | Scanners are a constructor arg, not a config field | Confirmed | `Pipeline.__init__(self, scanners: Sequence[Scanner] = (), *, config=...)`; no `scanners` field in `PetasosConfig` (config.py:43-109). |
| D8 | Config uses `to_dict`/`from_dict` for Hermes top-level `petasos:` key | Confirmed | `to_dict()`/`from_dict()` classmethods shipped (9e68599:petasos/config.py); enable top-level serialization. Current config.py:341/357. (YAML-key nesting is the consumer's concern; methods satisfy the decision.) |
| §4.3 | Merge tie-break: higher confidence wins, then higher severity, then both kept | Confirmed (shipped) | Shipped merge_findings: `if nxt.confidence > current.confidence` first, severity rank on tie (9e68599:petasos/pipeline.py). NOTE on disk the order is now reversed to severity-first (pipeline.py:88-95) — a later-ticket change, not PET-6. |
| §4.4 | `degraded`+partial ML failure → safe unchanged; all-ML failure → safe=False | Confirmed (shipped) | Shipped `_compute_safe`: degraded branch sets `safe=False` only on `all_ml_failure` (9e68599). Current disk pipeline.py:139-141 now blocks on partial too (later hardening) plus syntactic-error handling — outside PET-6. |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Pipeline runs end-to-end with 0/1/2/3 scanners | Met | Construction tests test_pipeline.py:94-119; fan-out tests :218-275. |
| 2 | Concurrent execution verified (timing assertion) | Met | `test_concurrent_execution` test_pipeline.py:226. |
| 3 | Finding dedup for overlapping ranges across scanners | Met | `merge_findings` (pipeline.py:58); `test_overlapping_deduplicated` :300, `test_same_position_different_scanners` test_finding_merge.py:86. |
| 4 | `degraded`: partial→pass, all-ML→block, syntactic always runs | Met | `_compute_safe` (pipeline.py:104); tests test_pipeline.py:347-376. |
| 5 | `open`: any failure → pass | Met | open branch `pass` (pipeline.py:142); tests :399-414. |
| 6 | `closed`: any failure → block; early exit on CRITICAL syntactic | Met | closed branch + `early_exit` (pipeline.py:144,413); tests :429-469. |
| 7 | Anonymization correct for all four operator modes | Met (within shipped scope) | Stage 9 calls `presidio.anonymize(..., mode=config.redaction_mode, ...)` (pipeline.py:501-516); tests `test_pii_findings_anonymize_true` :523, `test_mask_mode_deterministic` :581. Real Presidio backend exercised via integration per project test standard. |
| 8 | HMAC-SHA256 hash mode deterministic/correlatable | Unverifiable (delegated) | Pipeline passes `hash_key` through to `presidio.anonymize`; hash determinism is the PresidioScanner's contract, not pipeline code. Shipped pipeline test uses mask-mode determinism (`test_mask_mode_deterministic` :581) rather than HMAC. Behavior lives in presidio.py, out of PET-6 file scope. |
| 9 | Pipeline never throws — all error paths return valid result | Met | `inspect()` outer `try/except` returns `PipelineResult(safe=False,...)` (pipeline.py:363); tests `test_broken_scanner_returns_result` :599, `test_base_exception_caught_at_boundary` :624. |
| 10 | `PetasosConfig` serializes to/from dict, validates on construction | Met | `to_dict`/`from_dict` (config.py:341,357), `__post_init__` validation (config.py:111); `test_round_trip` test_config.py:80. |
| 11 | Constructor snapshots config (defensive copy) | Met | Shipped `copy.deepcopy` (9e68599); `test_config_defensive_copy` test_pipeline.py:119. (On disk now `replace()`, still a fresh copy.) |
| 12 | Premium hooks present as no-ops, callable without error | Met (shipped) | Four no-op hooks shipped (9e68599); `test_hooks_callable` :651, `test_hooks_are_noops` :659. (Hooks now carry real premium logic on disk from PET-7..9.) |
| 13 | `mypy --strict` and `ruff` clean on new files | Met | Shipped test-output.txt: "Success: no issues found in 2 source files" + "All checks passed!". |
| 14 | ≥60 tests across pipeline+config+merge | Met | 72 passed (test-output.txt); 46+15+12 = 73 test fns shipped. |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_config.py (≥10) | Yes (15) | tests/test_config.py |
| test_finding_merge.py (≥10) | Yes (12) | tests/test_finding_merge.py |
| test_pipeline.py (≥40) | Yes (46) | tests/test_pipeline.py |
| Construction: no-scanners→minimal only | Yes | test_pipeline.py:94 `test_no_scanners_uses_minimal_only` |
| Construction: explicit minimal not duplicated | Yes | test_pipeline.py:99 `test_explicit_minimal_not_duplicated` |
| Construction: ML separated; None config defaults; defensive copy | Yes | test_pipeline.py:107,114,119 |
| Normalization: normalized before scan / disabled→raw / empty safe | Yes | test_pipeline.py:133,154,175 |
| Pre-filter: always runs / findings included / error recorded | Yes | test_pipeline.py:189,197,203 |
| Fan-out: single, concurrent, exception isolated, timeout, empty | Yes | test_pipeline.py:218,226,238,252,268,275 |
| Merge: minimal+ml, overlap dedup, aggregate severity | Yes | test_pipeline.py:290,300,324 |
| Fail-mode degraded/open/closed suites | Yes | test_pipeline.py:347-469 |
| Anonymization (5) | Yes | test_pipeline.py:523-581 |
| Never-throws (4) incl. BaseException boundary | Yes | test_pipeline.py:599-624 |
| Premium hooks (2) | Yes | test_pipeline.py:651,659 |
| Direction parameter (2) | Yes | test_pipeline.py:674,693 |
| Merge: no/empty/single/non-overlapping/multi-scanner | Yes | test_finding_merge.py:33-58 |
| Merge: higher-conf, equal-conf→severity, double-tie, same-pos, unpositioned, mixed | Yes | test_finding_merge.py:66-108 |
| Config: defaults, round-trip, invalid direction/fail_mode/redaction, hash_key req, frozen, partial/extra-key, empty entities, premium stubs | Yes | test_config.py:11-220 |
| Test command (pytest + mypy --strict + ruff) | Passed | docs/specs/TODO/PET-6.test-output.txt — 72 passed, mypy/ruff clean |

## Wiki-ready
- D1 — `asyncio.gather` + per-scanner `Exception` wrapping (not `TaskGroup`): security scanners must finish independently; one slow/failing scanner must not cancel siblings. Constraining for all future scanner orchestration. (Note: master has since hardened the catch to `BaseException`+`return_exceptions=True`.)
- D7 — scanners are a `Pipeline.__init__` argument, not a `PetasosConfig` field: resolves the brief's conflict between "scanners in config" and "every field JSON-serializable." Separates non-serializable runtime objects from declarative config; constrains the config schema permanently.
- D2 — MinimalScanner runs first/synchronously + closed-mode CRITICAL early-exit: establishes the always-on syntactic baseline and the closed-mode short-circuit semantics later tickets build on.

RECONCILED: yes DRIFT: 1
