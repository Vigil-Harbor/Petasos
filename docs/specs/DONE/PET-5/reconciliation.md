# Reconciliation Report: PET-5

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-5.spec.md
> Merge: PR #4 (c74c838)
> Plane state: Done (group: completed)

## Summary
PET-5 shipped at c74c838 (PR #4) exactly as specced: `PresidioScanner` + standalone `anonymize()` with all four modes, severity map, lazy-load, and 47 tests (spec required ≥20). All acceptance criteria were met at ship time, including the plain-SHA256 fallback; the diff also carried sibling-scanner/CI cleanup not named in the spec (counted as drift).

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/presidio.py` (create) | Yes | New, +323. PresidioScanner + anonymize() + `_HmacSha256Operator` |
| `tests/test_presidio_scanner.py` (create) | Yes | New, +490. 47 test functions |
| `petasos/scanners/__init__.py` (modify) | Yes | +11. try/except conditional re-export of `PresidioScanner`, `anonymize` matching PET-3 pattern |

Unexpected files in diff (not in spec):
- `pyproject.toml` (+20) — spec "Files to leave alone" explicitly says no changes (extras already defined). Diff adds mypy per-module `ignore_missing_imports` overrides for optional scanner deps (CI fix). Drift.
- `petasos/scanners/llm_guard.py` (−1) — removed redundant `type: ignore`. Sibling-scanner cleanup, not in spec. Drift.
- `petasos/scanners/llama_firewall.py` (−1) — removed redundant `type: ignore`. Sibling-scanner cleanup, not in spec. Drift.
- `tests/test_llama_firewall_scanner.py` (−1) — minor sibling test fix, not in spec. Drift.
- `docs/specs/TODO/PET-5.test-output.txt` (new, +139) — ship-spec test-output artifact, not in spec. Drift (routine artifact).

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | `_ensure_loaded()` instantiates both engines, raises on failure, lock-guarded; error cached and re-raised | Confirmed | presidio.py:113-133 — both `AnalyzerEngine()`+`AnonymizerEngine()` created, `self._load_error` cache/re-raise, `self._load_lock` (threading.Lock) |
| 2 | RecognizerResult → ScanFinding mapping (finding_type="pii", rule_id `petasos.presidio.{type}`, Position, confidence, matched_text, message) | Confirmed | presidio.py:180-195 (`_scan_sync`) |
| 3 | Severity mapping by entity-type category (frozen `_SEVERITY_MAP`, unknown→LOW) | Confirmed | presidio.py:23-38; default `Severity.LOW` at presidio.py:182 |
| 4 | Constructor params plumbed to `analyze()` (entities/language/score_threshold) | Confirmed | presidio.py:172-178 |
| 5 | Scan runs synchronously via `asyncio.to_thread` | Confirmed | presidio.py:145 `await asyncio.to_thread(self._scan_sync, text)` |
| 6 | Dual-path anonymization (engine: redact/hash; manual: replace/mask) | Confirmed | presidio.py:245-248 dispatch; `_anonymize_engine_path` / `_anonymize_manual_path` |
| 7 | Custom HMAC operator (`_HmacSha256Operator`) registered via `add_anonymizer()`, four ABC methods | Confirmed | presidio.py:67-89 (factory `_make_hmac_operator_class`); registered at :62 and :129 |
| 8 | Replace mode uses entity-scoped counters (`<PERSON_1>`, increment-then-use, resets per call) | Confirmed | presidio.py:304-321 (`defaultdict(int)`, forward labeling, reverse application) |
| 9 | Mask mode hides leading chars, shows trailing 4; ≤4 fully masked; matched_text fallback | Confirmed | presidio.py:329-338 (`visible = 4`, `text[start:end]` fallback) |
| 10 | Hash mode: HMAC-SHA256 with key, plain SHA256 fallback when key is None | Confirmed (at ship) | At c74c838 `_anonymize_engine_path` used `OperatorConfig("hash",{"hash_type":"sha256"})` when `hash_key is None`. NOTE: superseded post-ship by PET-63 (73ab2ec, PR #29) which now raises ValueError on missing/empty key — see Wiki-ready |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | PresidioScanner implements Scanner protocol | Met | presidio.py:92; test `TestScannerProtocol.test_satisfies_protocol` (isinstance check) |
| 2 | Lazy-load import failure → errored ScanResult, no crash | Met | presidio.py:152-159; test `test_import_error_returns_errored_result` |
| 3 | spaCy model missing → clear error in ScanResult.error, no crash | Met | presidio.py:160-170 (spacy/model msg rewrite); test `test_spacy_model_missing` |
| 4 | Constructor params entities/language/score_threshold functional | Met | presidio.py:93-102, 172-178; tests `test_score_threshold_filtering`, `test_custom_entities_filter` |
| 5 | RecognizerResult→ScanFinding mapping populated | Met | presidio.py:184-195; integration tests assert position/matched_text/severity |
| 6 | Severity mapping CRITICAL/HIGH/MEDIUM/LOW | Met | presidio.py:23-38; `TestSeverityMapping` |
| 7 | name property returns "presidio" | Met | presidio.py:110-111; `test_name_property` |
| 8 | Duration tracking via time.perf_counter | Met | presidio.py:142,146; `test_duration_tracked` |
| 9 | scan() wraps sync call in asyncio.to_thread | Met | presidio.py:145 |
| 10 | anonymize(text, findings, mode, hash_key=None) exported | Met | presidio.py:228; scanners/__init__.py:42-44 re-export |
| 11 | All four modes correct (redact/replace/hash/mask) | Met | engine + manual paths; `TestAnonymizeRedact/Replace/Hash/Mask` |
| 12 | HMAC-SHA256 deterministic/correlatable (same input+key=same hash) | Met | presidio.py:83-87; `test_hmac_deterministic`, `test_different_keys_produce_different_hashes` |
| 13 | Plain SHA256 fallback when no key | Met (at ship) | c74c838 presidio.py engine path `hash_type="sha256"` when `hash_key is None`; shipped test `test_hash_without_key_uses_sha256`. (Later superseded by PET-63.) |
| 14 | Replace mode entity-scoped counters | Met | presidio.py:304-313; `test_counter_based_labels` |
| 15 | Mask mode hides leading, shows trailing | Met | presidio.py:329-338; `test_mask_hides_leading`, `test_mask_short_value_fully_masked` |
| 16 | Manual-path overlap resolution (higher confidence wins, longer-span tiebreaker) | Met | presidio.py:205-225 (`_resolve_overlaps`); `test_overlapping_manual_path_deduplicates`, `test_overlapping_higher_confidence_wins` |
| 17 | matched_text=None fallback to text[start:end] | Met | presidio.py:333; `test_mask_matched_text_none_fallback` |
| 18 | Anonymizer handles unsorted findings (internal sort) | Met | presidio.py:210,305-307,324-328; `test_reverse_order_input_handled` |
| 19 | Findings without position silently skipped | Met | presidio.py:241-243; `test_all_unpositioned_findings_returns_original`, `test_unpositioned_findings_skipped` |
| 20 | _ensure_loaded guarded by threading.Lock | Met | presidio.py:107,118 |
| 21 | Integration tests vs real presidio-analyzer, 20-msg PII corpus | Met | `TestPresidioScannerIntegration` (13 cases) + `TestAnonymizeIntegration` (4) cover CC/SSN/email/phone/person/clean/multi/position |
| 22 | pip install petasos[presidio] succeeds in clean 3.11 venv | Unverifiable | Environment claim; extras pin present in pyproject; not reproducible read-only |
| 23 | Fail-open verified under backend exception | Met | presidio.py:160-170; `test_backend_exception_during_analyze` |
| 24 | ≥20 tests passing | Met | 47 test functions in shipped tests/test_presidio_scanner.py |
| 25 | mypy --strict clean | Unverifiable | CI-time claim; pyproject overrides added for this; not re-run read-only |
| 26 | ruff check / ruff format clean | Unverifiable | CI-time claim; not re-run read-only |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| Severity mapping completeness + unknown→LOW | Yes | tests/test_presidio_scanner.py `TestSeverityMapping` |
| Finding/entity-type recovery round-trip | Yes | `TestEntityTypeRecovery` |
| Counter-based replace labels + reset across calls | Yes | `TestAnonymizeReplace.test_counter_based_labels`, `test_counter_resets_across_calls` |
| Detection corpus (CC/SSN/email/phone/person/clean/multi) | Yes | `TestPresidioScannerIntegration` |
| Position accuracy | Yes | `test_position_accuracy` |
| Confidence range 0<c≤1 | Yes | `test_confidence_range` |
| Scanner protocol compliance + name | Yes | `TestScannerProtocol` |
| Anonymization modes redact/replace/hash(+/-key)/mask | Yes | `TestAnonymizeRedact/Replace/Hash/Mask` |
| Hash correlation (same/diff key) | Yes | `test_hmac_deterministic`, `test_different_keys_produce_different_hashes` |
| Unsorted findings | Yes | `TestAnonymizeUnsortedFindings` |
| Overlapping (manual path) | Yes | `TestAnonymizeOverlap` |
| matched_text=None fallback | Yes | `test_mask_matched_text_none_fallback` |
| All-unpositioned / empty findings / empty text | Yes | `TestAnonymizeEmptyInputs` |
| Score threshold filtering | Yes | `test_score_threshold_filtering` |
| Lazy-load import / spaCy missing / backend exception | Yes | `TestLazyLoadFailure` |

## Wiki-ready
- **Plain-SHA256-fallback decision (spec D10/criterion 13) was deliberately reversed after ship by PET-63 (73ab2ec, PR #29).** PET-5 shipped unkeyed `mode="hash"` as plain SHA256; PET-63 now raises ValueError requiring a non-empty `hash_key` because unkeyed hashing is brute-force-reversible on low-entropy PII. Reconciling against the canonical PET-5 commit (c74c838) the criterion is Met; readers of current `presidio.py` will see the stricter PET-63 behavior. This is a genuine, constraining cross-ticket decision worth recording, not PET-5 drift.

RECONCILED: yes DRIFT: 5
