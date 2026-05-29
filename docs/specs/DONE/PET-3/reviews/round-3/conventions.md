# Conventions Review -- round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| conventions | F-1 | PET-3 and PET-4 disagree on `petasos/__init__.py` top-level re-export strategy | CLOSED | PET-4 spec (round 2 revision) line 383: "petasos/__init__.py: Not modified. ML-backend scanners are available via petasos.scanners, not the top-level petasos namespace, consistent with PET-3's convention." Both specs now agree: no top-level re-export. |
| conventions | F-2 | PET-3 and PET-4 use incompatible `scanners/__init__.py` re-export patterns | CLOSED | PET-4 spec (round 2 revision) lines 367-379: now uses identical `try/except ImportError` with `__all__.append()` pattern, explicitly noting "The pattern matches PET-3's approach for cross-sibling consistency." |
| conventions | F-3 | `_ensure_loaded` double-state pattern differs from PET-4's single-state pattern | OPEN | PET-3 spec lines 130-145: sets `_loaded = True` only on success (line 143), checks `_load_error` separately outside and inside the lock. PET-4 spec lines 185-236: sets `_loaded = True` eagerly before try (line 191), returns `bool`. PET-3 returns `None`. The two patterns remain structurally different, though both work correctly. PET-3 added the inner `_load_error` check (line 138-139) which closes the edge-cases F-1 race. The state-machine divergence is still present but both implementations are correct. Downgrading to P3 advisory since both specs are internally consistent and correct. |
| conventions | F-4 | Sub-scanner registry uses bare `list[tuple]`, not `MappingProxyType` | OPEN | PET-3 spec line 128: `_scanners: list[tuple[str, str, Severity, Any]]` remains mutable. PET-4 uses `MappingProxyType` for its taxonomy constant (PET-4 lines 99-115). The taxonomy data (rule_id, finding_type, severity mappings) in PET-3 is only shown as a markdown table (lines 168-175), not as a frozen code constant. Still divergent from PET-4's approach. Keeping at P3. |
| conventions | F-5 | `reset()` method is a silent spec addition not authorized by the brief | CLOSED | Spec D3b (line 57-59) includes explicit rationale for `reset()`. The expanded docstring (lines 148-154) now documents the safety contract. This is a (c)-class addition with adequate rationale. No further action needed. |
| conventions | F-6 | Integration test skip mechanism differs from PET-4 | CLOSED | PET-4 spec (round 2 revision) line 409: still uses `@pytest.mark.skipif(not _has_llamafirewall, ...)`. PET-3 still uses `pytest.importorskip`. The divergence remains but is P3 advisory and both approaches are valid pytest idioms. PET-4 line 381 explicitly acknowledges cross-sibling consistency on more load-bearing patterns. Accepting as a known minor inconsistency. |
| conventions | F-7 | `ban_topics` parameter accepted silently without `enable_ban_topics=True` | CLOSED | Spec test 10 (line 257) explicitly documents this as a design choice. The asymmetry is acknowledged. P3 advisory, no spec change required. |
| correctness | F-1 | `threshold` default 0.85 contradicts LLM Guard default 0.92 | OPEN | Spec D4 (line 63-68) still does not note the divergence from the library default. The brief authorizes 0.85, so it is correct, but the rationale gap remains. P2 clarity issue. |
| correctness | F-2 | `scanners/__init__.py` proposed content adds `MinimalScanner` re-export that doesn't exist today | OPEN | Spec line 23 scope still says "add conditional re-export of LlmGuardScanner" but the code block at lines 220-232 shows adding both `MinimalScanner` re-export AND the `LlmGuardScanner` guarded import. The scope description understates the change. P2 accuracy issue. |
| correctness | F-3 | Done-when "10 detection scenarios" vs brief "20-message corpus" | OPEN | Spec done-when line 307 says "10 detection scenarios" without acknowledging departure from brief's "20-message corpus" (brief line 82). No reconciliation note added. P2 drift from brief. |
| correctness | F-4 | `_scan_sync` return unpacking may not match all sub-scanners (Secrets/InvisibleText always 1.0) | OPEN | No note added to D4 about non-discriminating confidence for Secrets and InvisibleText. P2 documentation gap. |
| correctness | F-5 | Done-when says ">= 20 tests" but parenthetical sums to 24 | OPEN | Spec line 309: ">= 20 tests passing (14 unit + 10 integration)" -- parenthetical still sums to 24, floor says 20. Minor inconsistency remains. P3. |
| correctness | F-6 | Plane ticket not cached in memory | OPEN | Still not cached. P3 operational. |
| edge-cases | F-1 | `_ensure_loaded()` double-checked locking missing inner `_load_error` check | CLOSED | Spec lines 138-139: `if self._load_error is not None: return` now present inside the lock, with comment "another thread failed while we waited for the lock". |
| edge-cases | F-2 | `reset()` concurrent with `scan()` causes silent false-negative | CLOSED | Spec D3b (line 59): "reset() must not be called while scan() calls are in flight." Docstring (lines 148-154) expands on the safety contract with specific failure mode description. Caller-responsibility approach adopted. |
| edge-cases | F-3 | `_load_error` check in `scan()` redundant with `_ensure_loaded()` | OPEN | Spec scan() flow (lines 183-185) still uses the side-channel pattern. Now documented in spec Deferred section (line 347). P2, deferred. |
| edge-cases | F-4 | `_scan_sync` does not snapshot `_scanners` reference | OPEN | Now documented in spec Deferred section (line 348). P2, deferred. |
| edge-cases | F-5 | `ban_topics` constructor validation does not check element types | OPEN | Now documented in spec Deferred section (line 349). P2, deferred. |
| edge-cases | F-6 | Test 12 thread safety may not reliably detect the race | OPEN | No change in spec. P3 advisory. |
| edge-cases | F-7 | `_scan_sync` exception handler swallows exception type information | OPEN | No change in spec. P3 advisory. |
| edge-cases | F-8 | No test for `reset()` followed by successful re-load | OPEN | No test added. P3 advisory. |

## Findings

### F-1: `_ensure_loaded` state pattern still structurally diverges from PET-4
**Severity:** P3
**Where:** spec lines 130-145 vs PET-4 spec lines 184-236
**Convention violated:** Cross-spec consistency for sibling work items implementing the same lazy-load pattern
**Evidence:** PET-3 uses a three-state model (`_loaded=False/_load_error=None` = untried; `_loaded=False/_load_error!=None` = failed; `_loaded=True` = success) and returns `None`. PET-4 uses a two-state model (`_loaded=False` = untried; `_loaded=True` = tried, check `_load_error`) and returns `bool`. Both are correct. PET-3's round 3 revision added the inner `_load_error` check (line 138-139), closing the race from edge-cases F-1, so the functional outcome is now equivalent. The structural divergence is cosmetic -- implementers of one cannot copy-paste from the other, but both state machines are sound. Since both specs are internally consistent and both handle all concurrent paths correctly, this is advisory only.
**Suggested fix:** No change required. If a future PET-2 parent spec defines a canonical lazy-load template, both should converge on it. For now, documenting the difference as a known variation is sufficient.

### F-2: Sub-scanner taxonomy is a markdown table, not a frozen code constant
**Severity:** P3
**Where:** spec lines 168-175 (markdown table) vs PET-4 lines 99-115 (`MappingProxyType`)
**Convention violated:** CLAUDE.md: "Frozen exports -- built-in profiles, rules, and default configs must be immutable (defensive copies, frozen dataclasses)."
**Evidence:** PET-4 wraps its component taxonomy in `MappingProxyType` at module level (PET-4 spec lines 99-115, 346-362). PET-3's equivalent data (rule_id, finding_type, severity per sub-scanner) is shown only as a markdown table (spec lines 168-175) and as inline logic inside `_ensure_loaded()`. The runtime `_scanners` list at line 128 is mutable. The taxonomy mappings themselves (which are static configuration, not runtime state) are not frozen. This matters less for PET-3 than PET-4 because PET-3's tuple-based `_scanners` list holds scanner *instances* that must be mutable, while the mapping from sub-scanner name to (rule_id, finding_type, severity) is genuinely static. Extracting the static portion into a frozen constant would align with PET-4 and the frozen-exports invariant.
**Suggested fix:** Extract the five-row taxonomy into a module-level `_SUB_SCANNER_TAXONOMY` constant (tuple-of-tuples or `MappingProxyType`) matching PET-4's approach. The runtime `_scanners` list can remain mutable since it holds scanner instances.

### F-3: `scanners/__init__.py` scope description understates the actual change
**Severity:** P2
**Where:** spec line 23 ("add conditional re-export of LlmGuardScanner") vs spec lines 220-232 (code block)
**Convention violated:** Scope accuracy -- the scope section should describe the full delta, not a subset
**Evidence:** The existing `petasos/scanners/__init__.py` is effectively empty (1 line, no imports, no `__all__`). The spec's code block at lines 220-232 shows adding `from petasos.scanners.minimal import MinimalScanner`, `__all__ = ["MinimalScanner"]`, and the `try/except` for `LlmGuardScanner`. The scope description at line 23 says only "add conditional re-export of LlmGuardScanner" -- it omits the `MinimalScanner` re-export, which is a new addition. An implementer reading only the scope section would miss this. PET-4's scope section (PET-4 line 29) says "Re-export LlamaFirewallScanner (guarded, additive)" which has the same gap but at least says "additive." The `MinimalScanner` re-export in `scanners/__init__.py` does not break anything (it's a convenience path) but it is an unremarked scope expansion.
**Suggested fix:** Update spec line 23 to: "add `MinimalScanner` re-export and conditional `LlmGuardScanner` re-export to `__all__`"

### F-4: Done-when "10 detection scenarios" silently weakens brief's "20-message corpus" criterion
**Severity:** P2
**Where:** spec line 307 vs brief line 82
**Convention violated:** Silent spec additions (category d) -- the spec commits to a weaker position than the brief without flagging the departure
**Evidence:** Brief done-when (line 82): "Integration tests against real `llm-guard` backend (not mocked) with 20-message corpus." Spec done-when (line 307): "Integration tests against real `llm-guard` backend (not mocked) covering 10 detection scenarios with distinct adversarial inputs." The spec reduced the count from 20 to 10 without acknowledgment. PET-4's spec (lines 421-422) includes a "Corpus: 20-message scan" test with an explicit fixture, showing the sibling scanner spec honors the "20-message" criterion. PET-3 diverges without explanation. The 10 integration tests may cover the detection surface adequately, but the departure from the brief's stated criterion should be acknowledged.
**Suggested fix:** Either (a) add a 20-message corpus test matching PET-4's approach (test 22 in PET-4), or (b) add a note in done-when or Deferred: "Brief specified '20-message corpus'; spec defines 10 scenario-based integration tests covering all five sub-scanner detection surfaces, which satisfies the brief's detection breadth intent."

### F-5: Integration test skip mechanism diverges from PET-4
**Severity:** P4
**Where:** spec line 263 (`pytest.importorskip`) vs PET-4 line 409 (`@pytest.mark.skipif`)
**Convention violated:** Cross-spec consistency for sibling test files
**Evidence:** PET-3 uses `pytest.importorskip("llm_guard")` (function-level, produces "SKIPPED (module 'llm_guard' not available)" message). PET-4 uses `@pytest.mark.skipif(not _has_llamafirewall, ...)` (decorator-level, produces custom reason string, module-level boolean). Both are standard pytest idioms. The inconsistency is cosmetic -- test output reads differently but functionality is identical. Downgraded from round 2 P3 to P4 nit since both approaches are idiomatic and PET-4 explicitly acknowledges cross-sibling alignment on the more load-bearing `__init__.py` pattern.
**Suggested fix:** No change required. Future PET-2 test conventions doc could standardize on one approach.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 2 | P4: 1

STATUS: GREEN
