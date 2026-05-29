# Reconciliation Report: PET-1

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-1.spec.md
> Merge: PR #1 (5e4134c)
> Plane state: Done (group: completed)

## Summary
The PET-1 foundation (Scanner protocol, frozen types, normalizer, 17-rule MinimalScanner, scaffolding, CI) shipped substantially as specified in PR #1 with 68 passing tests. One decision drifted: the `confusables_normalized` flag is computed against the post-NFKC text (homoglyph-mapping only), not against the post-strip text as spec line 316 / D6 prescribe — so NFKC-only obfuscation does NOT set the flag, contrary to the spec.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| pyproject.toml | Yes | Hatch, py>=3.11, `dependencies = []` as specified (5e4134c) |
| ruff.toml | Yes | 8 lines; contents left to implementer per Deferred note |
| .github/workflows/ci.yml | Yes | 3 jobs (lint/typecheck/test), matrix 3.11/3.12/3.13 |
| petasos/__init__.py | Yes | Re-exports + `RULE_TAXONOMY`, matches spec section 5 verbatim |
| petasos/_types.py | Yes | Scanner, Severity, Position, ScanFinding, ScanResult, NormalizedText, PipelineResult stub |
| petasos/normalize.py | Yes | 4-step normalize; see Decision drift below |
| petasos/scanners/__init__.py | Yes | Empty package marker (spec scope line 28) |
| petasos/scanners/minimal.py | Yes | 17 rules across 4 categories |
| petasos/py.typed | Yes | PEP 561 marker (empty) |
| tests/__init__.py | Yes | Empty (spec scope line 31) |
| tests/conftest.py | Yes | 1 line |
| tests/test_types.py | Yes | 15 tests |
| tests/test_normalize.py | Yes | 22 tests |
| tests/test_minimal_scanner.py | Yes | 31 tests |

Unexpected files in diff (not in spec):
- `.coderabbit.yaml` (15 lines) — review-tooling config, not in spec scope.
- `docs/specs/TODO/PET-1.test-output.txt` (79 lines) — ship-spec test-evidence artifact, not in spec scope.
- `.gitignore` (+3 lines, `docs/research/`) — spec line 43 explicitly listed `.gitignore` under "Files to leave alone."

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Curated 17-char homoglyph table, not full ICU | Confirmed | `5e4134c:petasos/normalize.py` `_HOMOGLYPH_TABLE` has exactly 17 entries (8 Cyrillic, 7 Greek, 1 Latin dotless-i, 1 IPA g) |
| D2 | `petasos.*` namespace for rule IDs | Confirmed | `5e4134c:petasos/scanners/minimal.py:67` `f"petasos.syntactic.injection.{slug}"`; all rule-id sets prefixed `petasos.syntactic.*` |
| D3 | Frozen dataclasses; to_dict/from_dict on ScanFinding+ScanResult only | Confirmed | `5e4134c:petasos/_types.py` all result types `@dataclass(frozen=True)`; `to_dict`/`from_dict` on ScanFinding (L34-64) and ScanResult (L71-89) only; PipelineResult/NormalizedText have none |
| D4 | pytest-asyncio `mode="auto"` | Confirmed | `5e4134c:pyproject.toml` `[tool.pytest.ini_options] asyncio_mode = "auto"`; `pytest-asyncio>=0.23` in dev extras |
| D5 | RTL override: detect+flag, don't strip | Confirmed | `5e4134c:petasos/normalize.py` `rtl_detected = bool(RTL_OVERRIDES & set(text))`; RTL chars set flag, only `INVISIBLE_CHARS` are removed |
| D6 | Homoglyph-substitution fires unconditionally | Confirmed | `5e4134c:petasos/scanners/minimal.py:366-369` gates only on `"homoglyph_mapped" in normalized.transformations_applied`, no injection co-occurrence guard |
| D7 | Suppression: prevents execution; structural unsuppressible; escalation uses non-suppressed injection | Confirmed | `minimal.py:111` `suppress_rules - _STRUCTURAL_RULE_IDS` (only structural excluded; injection still suppressible per spec); `_check_injection` skips suppressed rules and only sets `any_matched` for non-suppressed matches (L250-271) |
| — | `confusables_normalized` computation (spec Design §3 line 316: flag set when text after steps 3+4 differs from text after step 2; "NFKC-only obfuscation ... must set the flag") | Drifted | `5e4134c:petasos/normalize.py` `confusables = text_after_homoglyph != text_after_nfkc` — compares against post-NFKC, so NFKC-only changes do NOT set the flag. Squashed fix commits cc87212/2bae271 deliberately narrowed this, contradicting the merged spec text. (Homoglyph finding itself keys off `homoglyph_mapped`, so detection still works; the divergence is the flag semantics.) |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `pip install -e .` succeeds in clean 3.11 venv, zero ML deps | Met | `5e4134c:pyproject.toml` `dependencies = []`; scanner backends are optional extras |
| 2 | `mypy --strict .` passes | Unverifiable | Not re-run here (read-only reconcile); CI `typecheck` job runs `mypy --strict .` and PR #1 merged green |
| 3 | `ruff check . && ruff format --check .` passes | Unverifiable | Not re-run; CI `lint` job enforces both; squash commit 9df5aa6 applied ruff formatting |
| 4 | MinimalScanner detects all 17 rule categories | Met | `RULE_TAXONOMY` = 17 IDs; `test_minimal_scanner.py` covers 8 injection + 2 role-switch + 3 structural + 4 encoding; `test_17_rules` asserts count |
| 5 | Normalization strips zero-width, maps homoglyphs, flags RTL | Met | `5e4134c:petasos/normalize.py` strips `INVISIBLE_CHARS`, applies `_HOMOGLYPH_TABLE`, sets `rtl_overrides_detected`; tests in `test_normalize.py` |
| 6 | >=50 tests passing | Met | `5e4134c:docs/specs/TODO/PET-1.test-output.txt` ends `68 passed in 0.07s` |
| 7 | Scanner protocol implementable by trivial stub | Met | `5e4134c:tests/test_types.py` `_StubScanner` + `test_runtime_checkable` (`isinstance(stub, Scanner)`) |
| 8 | All result types frozen (mutation raises FrozenInstanceError) | Met | `test_types.py` frozen tests for ScanFinding/ScanResult/PipelineResult/NormalizedText |
| 9 | GitHub Actions CI stub runs lint+typecheck+tests | Met | `5e4134c:.github/workflows/ci.yml` three jobs on ubuntu-latest, test matrix 3.11/3.12/3.13 |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| test_types.py — protocol/frozen/roundtrip (~15) | Yes | `5e4134c:tests/test_types.py` (TestScannerProtocol, TestScanFinding, TestScanResult, TestPipelineResult, TestNormalizedText, TestPosition, TestSeverity, TestDirection) |
| test_normalize.py — NFKC/invisible/RTL/homoglyph (~20) | Yes | `5e4134c:tests/test_normalize.py` 22 tests; incl. `test_nfkc_only_does_not_set_confusables` (encodes the drift), `test_line_separator_not_stripped` |
| test_minimal_scanner.py — 8 injection + role-switch + structural + encoding + escalation + suppression (~28) | Yes | `5e4134c:tests/test_minimal_scanner.py` 31 tests; incl. `test_invisible_plus_injection_escalates`, `test_structural_cannot_be_suppressed`, `test_homoglyph_fires_unconditionally_d6`, `test_deep_nesting_no_recursion_error`, `test_exception_guard` |

## Wiki-ready
- D6 — homoglyph-substitution fires unconditionally (deliberate divergence from Drawbridge's injection-co-occurrence gate); constrains downstream PET-6/PET-8 to suppress false positives by severity rather than relying on the scanner to gate.
- D7 — suppression prevents rule *execution* (not just output filtering), structural rules are silently unsuppressible, and escalation keys off *non-suppressed* injection matches. Reusable invariant for any later scanner work.
- `confusables_normalized` semantics drift: the flag tracks homoglyph mapping only, NOT NFKC-only changes — opposite of the merged spec's stated computation. Worth recording so future readers don't trust the spec text over the code; `test_nfkc_only_does_not_set_confusables` is the canonical witness.

RECONCILED: yes DRIFT: 4
