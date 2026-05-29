# Reconciliation Report: PET-4

> Date: 2026-05-28
> Spec: docs/specs/TODO/PET-4.spec.md
> Merge: PR #3 (2333622)
> Plane state: Done (group: completed)

## Summary
The shipped `LlamaFirewallScanner` (commit 2333622, PR #3) matches the spec's intent in full: per-component `LlamaFirewall` instances, lazy-load with double-checked locking, `asyncio.to_thread` wrapping, tuple-return partial-failure design, and the immutable component taxonomy. All acceptance criteria are Met or Unverifiable (integration tests require the optional backend, which is not installed); zero criteria are Unmet.

## Scope
| Spec file | In diff? | Notes |
|---|---|---|
| petasos/scanners/llama_firewall.py (create) | Yes | 185 lines; implements `LlamaFirewallScanner` exactly per Design sections 1–6 |
| tests/test_llama_firewall_scanner.py (create) | Yes | 587 lines; 34 tests shipped (11 unit + 11 mock-functional + 12 integration). Current on-disk file has grown to ~40 tests with later additive unit tests (e.g. `test_no_components_duration_tracked`, `test_single_component_enabled_no_error`, `test_all_disabled_warns_on_load`) |
| petasos/scanners/__init__.py (modify) | Yes | Guarded additive re-export added in diff; current on-disk version refactored into shared `_is_missing_package` helper by later commits (PET-5 / refactor), behavior preserved |

Unexpected files in diff (not in spec):
- docs/specs/TODO/PET-4.test-output.txt — test-gate evidence artifact (lint/format/mypy/pytest output); routine ship-spec companion, not source. The spec listed "All docs, specs, briefs" under leave-alone but this is a generated audit artifact, not a spec edit.

## Decisions
| # | Decision | Status | Evidence |
|---|---|---|---|
| D1 | Use `LlamaFirewall` orchestrator class, one-entry scanners dict per component | Confirmed | llama_firewall.py:92-97 `LlamaFirewall(scanners={Role.USER: [scanner_type], Role.ASSISTANT: [scanner_type]})` |
| D2 | Lazy-load via `_ensure_loaded()` on first scan | Confirmed | llama_firewall.py:59-113; import inside method at :67-74 |
| D3 | BLOCK→finding, ALLOW→none, score→confidence (clamped), reason→message | Confirmed | llama_firewall.py:130-148; clamp at :133-135 |
| D4 | Per-component rule_id/finding_type/severity taxonomy | Confirmed | llama_firewall.py:15-33 `_COMPONENT_TAXONOMY` (prompt-guard/injection/HIGH, alignment-check/alignment/HIGH, code-shield/unsafe_code/MEDIUM) |
| D8 | Wrap sync `scan()` in `asyncio.to_thread()` | Confirmed | llama_firewall.py:181 `await asyncio.to_thread(self._scan_sync, text, direction)` |
| D9 | `position` and `matched_text` always `None` | Confirmed | llama_firewall.py:145-146 |
| D11 | Unpinned `llamafirewall` dep | Unverifiable | pyproject.toml outside diff scope (spec left it alone); D11 carried from brief, not a code change in PET-4 |
| DS1 | Per-component instances for attribution | Confirmed | llama_firewall.py:90-97 loop creates one `LlamaFirewall` per enabled component |
| DS2 | Direction→message-type mapping (inbound=User, outbound=Assistant) | Confirmed | llama_firewall.py:119-122; both roles mapped per component at :93-95 |
| DS3 | Per-component error isolation via tuple return | Confirmed | llama_firewall.py:115 signature `tuple[list[ScanFinding], list[str]]`; per-comp try/except at :128-150; join at :183 |
| DS4 | Non-ALLOW (not just BLOCK) → finding, via enum compare | Confirmed | llama_firewall.py:130 `if result.decision != self._allow_decision`; enum value cached at :78 |

## Acceptance Criteria
| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Class implements Scanner protocol | Met | llama_firewall.py:36; test_protocol_conformance (tests:162) |
| 2 | Import fail → errored ScanResult, no crash | Met | llama_firewall.py:104-108, scan:163-170; test_import_failure_returns_error (tests:165) |
| 3 | Constructor defaults (PG=True, others False) | Met | llama_firewall.py:40-42; test_default_constructor (tests:234) |
| 4 | Per-component instances from enable flags | Met | llama_firewall.py:80-97 |
| 5 | `scan()` wraps in `asyncio.to_thread()` | Met | llama_firewall.py:181 |
| 6 | Non-ALLOW → finding with correct fields | Met | llama_firewall.py:130-148; test_block_produces_finding (tests:283) |
| 7 | Per-component attribution: distinct rule_id prefixes | Met | _COMPONENT_TAXONOMY (llama_firewall.py:15-33); test_multiple_components (tests:376) |
| 8 | `name` returns "llama_firewall" | Met | llama_firewall.py:57; test_name (tests:159) |
| 9 | Duration tracking via perf_counter | Met | llama_firewall.py:161,182; test_duration_tracking (tests:249) |
| 10 | Integration tests vs real backend, 20-msg corpus | Unverifiable | test_corpus (tests:557) defines exactly 20 messages (10+5+3+2); SKIPPED — llamafirewall not installed (shipped test-output.txt: 12 skipped) |
| 11 | `pip install petasos[llamafirewall]` succeeds in clean venv | Unverifiable | Environment/install-time check; not asserted in code |
| 12 | Fail-open under backend exception | Met | scan outer try/except llama_firewall.py:190-197; test_exception_in_scan_returns_error (tests:255) |
| 13 | Partial failure: one component errors → others preserved | Met | llama_firewall.py:128-150; test_partial_failure_preserves_findings (tests:397) |
| 14 | ≥15 tests passing | Met | Shipped test-output.txt: 22 passed, 12 skipped (34 collected) |
| 15 | mypy --strict clean | Met | Shipped test-output.txt: "Success: no issues found in 12 source files / ---MYPY-OK---" |
| 16 | ruff check / format clean | Met | Shipped test-output.txt: ---RUFF-CHECK-OK--- / ---RUFF-FORMAT-OK--- |

## Test Plan
| Test | Exists? | Location |
|---|---|---|
| name property | Yes | tests/test_llama_firewall_scanner.py:159 test_name |
| Protocol conformance | Yes | tests:162 test_protocol_conformance |
| Import failure → errored ScanResult | Yes | tests:165 test_import_failure_returns_error |
| Import failure message | Yes | tests:172 test_import_failure_message |
| Init failure → errored ScanResult | Yes | tests:179 test_init_failure_returns_error |
| No components enabled | Yes | tests:193 test_no_components_enabled |
| Default constructor | Yes | tests:234 test_default_constructor |
| Thread safety of _ensure_loaded | Yes | tests:240 test_thread_safety |
| Duration tracking | Yes | tests:249 test_duration_tracking |
| Exception in scan body | Yes | tests:255 test_exception_in_scan_returns_error |
| Empty string input | Yes | tests:269 test_empty_string |
| Mock: block/allow/clamp/direction/partial/none-score/fail-once | Yes | tests:282-467 (TestMockFunctional, 11 tests) |
| Integration: jailbreak/clean/codeshield/alignment/directions/fields/partial/range/corpus/async | Yes (skipped) | tests:468-616 (TestIntegration, 12 tests) |
| 20-message corpus | Yes (skipped) | tests:557 test_corpus — 10 benign + 5 jailbreak + 3 unsafe code + 2 adversarial CoT |

## Wiki-ready
- DS1 (per-component `LlamaFirewall` instances) — non-obvious and constraining: LlamaFirewall's aggregated verdict cannot attribute which scanner triggered, so Petasos pays N sequential sync calls to get per-component rule_id/severity. Sets the latency tradeoff baseline for PET-6 (parallel execution deferred).
- D8 / DS4 details — `LlamaFirewall.scan()` internally calls `asyncio.run()`, so it cannot run in a live event loop; `to_thread` is mandatory, not just an optimization. Non-ALLOW (incl. HUMAN_IN_THE_LOOP_REQUIRED) maps to a finding via cached enum value, conservative-by-default. Reusable pattern for future async-incompatible ML wrappers.

RECONCILED: yes DRIFT: 0
