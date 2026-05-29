# Conventions Review -- round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| conventions | F-1 | rule_id naming three-segment vs four-segment undocumented | CLOSED | spec line 167: "Note on `rule_id` naming" paragraph explicitly documents the difference and rationale |
| conventions | F-2 | `_ensure_loaded` not thread-safe unlike PET-4 | CLOSED | spec lines 123-128, 130-151: `threading.Lock` with double-checked locking added, D3a decision added |
| conventions | F-3 | `__init__.py` re-export pattern diverged from PET-4 | CLOSED | spec lines 218-236: `try/except ImportError` with `__all__` population and explanatory note |
| conventions | F-4 | Test command hardcoded python3.13 | CLOSED | spec line 287: now reads `pytest tests/test_llm_guard_scanner.py -v` |
| conventions | F-5 | Unit tests mock import machinery, tension with CLAUDE.md | CLOSED | spec line 246: clarifying note added distinguishing sub-scanner mocks from Scanner protocol mocks |
| conventions | F-6 | Done-when "20-message corpus" not reflected in test plan | CLOSED | spec line 305: done-when now reads "10 detection scenarios with distinct adversarial inputs" matching the 10 integration tests |
| conventions | F-7 | Per-sub-scanner error isolation unauthorized by brief | CLOSED | spec lines 195-196, 209-210: code block now includes per-scanner try/except with error collection |
| conventions | F-8 | D3 threading strategy unauthorized by brief | CLOSED | spec line 51: "Spec addition (not in brief)" note with rationale added |
| conventions | F-9 | `petasos/__init__.py` omitted from scope | CLOSED | spec lines 27-28: explicit "Files left alone" entry with rationale |
| conventions | F-10 | Code samples omit `from __future__ import annotations` | CLOSED | spec lines 85, 122: both code samples now include the import |
| correctness | F-1 | `_scan_sync` code block missing per-scanner try/except | CLOSED | spec lines 196-210: code block now wraps each sub-scanner call in try/except |
| correctness | F-2 | `scan()` flow no path for partial-failure errors to reach ScanResult.error | CLOSED | spec lines 178, 183: `findings, errors = await asyncio.to_thread(...)` with `error="; ".join(errors)` |
| correctness | F-3 | `enable_ban_topics=True` with `ban_topics=None` unspecified failure | CLOSED | spec lines 98-101: eager `ValueError` at construction time |
| correctness | F-4 | "20-message corpus" done-when no corresponding test | CLOSED | spec line 305: done-when revised to "10 detection scenarios" |
| correctness | F-5 | Test command hardcodes python3.13 | CLOSED | spec line 287: changed to `pytest` |
| edge-cases | F-1 | Thread-safety race in `_ensure_loaded` | CLOSED | spec D3a, lines 130-151: `threading.Lock` with double-checked locking |
| edge-cases | F-2 | `_scan_sync` return type does not carry errors | CLOSED | spec lines 188-211: returns `tuple[list[ScanFinding], list[str]]` |
| edge-cases | F-3 | `enable_ban_topics=True` with `ban_topics=None` crash | CLOSED | spec lines 98-101: `ValueError` at construction time |
| edge-cases | F-4 | No validation of `threshold` range | CLOSED | spec lines 333-334: deferred as P2 with rationale |
| edge-cases | F-5 | Empty string input to `scan()` | CLOSED | spec line 326: documented in Out of scope section |
| edge-cases | F-6 | `_ensure_loaded` failure leaves `_loaded` state ambiguous on retry | CLOSED | spec D3b, lines 57-59: cached load failure pattern with `_load_error` and `reset()` |
| edge-cases | F-7 | Frozen dataclass error field plumbing | CLOSED | spec lines 178-185: all accumulation happens before `ScanResult` construction |
| edge-cases | F-8 | Very large input text | CLOSED | spec lines 325: documented in Out of scope section |
| edge-cases | F-9 | `direction="outbound"` test only checks non-crash | CLOSED | spec line 274: test now asserts findings are still produced |
| edge-cases | F-10 | `__init__.py` hides unexpected import errors | CLOSED | spec lines 335-336: deferred as P2 with rationale |
| edge-cases | F-11 | `isinstance` check passes for non-async scan | CLOSED | spec line 249: test 1 now includes `inspect.iscoroutinefunction` assertion |
| edge-cases | F-12 | No test for model download failure | CLOSED | spec line 261: test 14 added for model instantiation failure |

## Findings

### F-1: PET-3 and PET-4 disagree on `petasos/__init__.py` top-level re-export strategy
**Severity:** P2
**Where:** spec line 27 ("Files left alone") vs PET-4 spec line 29, 374
**Convention violated:** Cross-spec consistency for sibling work items (PET-3 and PET-4 are parallel children of PET-2)
**Evidence:** PET-3 spec line 27: "petasos/__init__.py -- LlmGuardScanner is not added to the top-level public API; consumers import from petasos.scanners directly." PET-4 spec line 29, 374: "petasos/__init__.py -- Add LlamaFirewallScanner to public API" and "Add LlamaFirewallScanner to imports and __all__." One sibling scanner is accessible via `petasos.LlamaFirewallScanner` and the other is not accessible via `petasos.LlmGuardScanner` -- consumers face an inconsistent import surface.
**Suggested fix:** Align with PET-4: either both scanners are available at the top-level `petasos` namespace (with guarded import), or neither is. Given that `MinimalScanner` is already re-exported in `petasos/__init__.py` (line 12 of the current file), the precedent favors top-level availability. Move `petasos/__init__.py` from "Files left alone" to "Modified files" with a guarded re-export matching the `scanners/__init__.py` pattern.

### F-2: PET-3 and PET-4 use incompatible `scanners/__init__.py` re-export patterns
**Severity:** P2
**Where:** spec lines 218-232 vs PET-4 spec lines 366-370
**Convention violated:** Cross-spec consistency for sibling work items sharing the same file
**Evidence:** PET-3 proposes (spec lines 221-232): `from petasos.scanners.minimal import MinimalScanner` / `__all__ = ["MinimalScanner"]` / `try: from ... import LlmGuardScanner; __all__.append(...) except ImportError: pass`. PET-4 proposes (spec lines 367-369): `from petasos.scanners.llama_firewall import LlamaFirewallScanner` / `__all__ = [*globals().get("__all__", []), "LlamaFirewallScanner"]`. These two patterns collide when both are applied to the same file. PET-3 starts `__all__` from scratch with `["MinimalScanner"]`; PET-4 uses `globals().get("__all__", [])` expecting prior content. If PET-3 ships first, PET-4's pattern works. If PET-4 ships first, PET-3's pattern clobbers PET-4's export. PET-3's `try/except ImportError` is the correct approach for extras-gated scanners (PET-4's unconditional import would crash without the extra installed), but the two specs need to agree on a single composable pattern.
**Suggested fix:** Both specs should use the same composable pattern. PET-3's `try/except ImportError` with `__all__.append()` is the right mechanism. PET-4 should adopt it too, but that's PET-4's fix. For PET-3: add a note in the `__init__.py` section stating the pattern is designed to compose with PET-4 and PET-5 additions (each wrapping their import in `try/except ImportError` and appending to `__all__`).

### F-3: `_ensure_loaded` double-state pattern differs from PET-4's single-state pattern
**Severity:** P2
**Where:** spec lines 130-143 vs PET-4 spec lines 184-232
**Convention violated:** Cross-spec consistency for sibling work items implementing the same lazy-load pattern
**Evidence:** PET-4 sets `self._loaded = True` *before* the try block (PET-4 spec line 190), so on failure `_loaded` is `True` and `_load_error` is non-None. All subsequent checks only test `_loaded` and then `_load_error`. PET-3 sets `self._loaded = True` only on *success* (PET-3 spec line 141), and checks `_load_error` separately outside the lock (spec line 133). PET-3's pattern has a subtler structure: three states (`_loaded=False/_load_error=None` = not yet tried; `_loaded=False/_load_error!=None` = tried and failed; `_loaded=True/_load_error=None` = success) while PET-4 has two (`_loaded=False` = not yet tried; `_loaded=True` = tried, check `_load_error`). Both work under CPython's GIL, but the inconsistency means implementers of one cannot copy-paste from the other, and reviewers must reason about a different state machine for each. PET-3's check of `_load_error` outside the lock (line 133) relies on CPython memory ordering guarantees that would break under PEP 703 (free-threaded Python). PET-4's Deferred section already notes this risk.
**Suggested fix:** Adopt PET-4's single-state pattern: set `self._loaded = True` before the try block, check `_load_error` inside `scan()` after `_ensure_loaded()` returns. Add a note to Deferred about PEP 703 implications, matching PET-4.

### F-4: Sub-scanner registry uses a bare `list[tuple]`, not `MappingProxyType`, diverging from frozen-exports invariant
**Severity:** P3
**Where:** spec line 128 (`_scanners: list[tuple[str, str, Severity, Any]]`)
**Convention violated:** CLAUDE.md: "Frozen exports -- built-in profiles, rules, and default configs must be immutable (defensive copies, frozen dataclasses)."
**Evidence:** PET-4 wraps its equivalent taxonomy constant (`_COMPONENT_TAXONOMY`) in `MappingProxyType` (PET-4 spec lines 100-116, 340-359), explicitly referencing the frozen-exports invariant. PET-3's `_scanners` list is mutable after construction. The module-level sub-scanner table (spec lines 159-166) is only shown as a markdown table, not as a frozen constant. While `_scanners` is populated at runtime (during lazy-load), the taxonomy mappings (rule_id, finding_type, severity per sub-scanner) are static and could be frozen.
**Suggested fix:** Extract the static sub-scanner taxonomy into a module-level frozen constant (e.g., `MappingProxyType` or a tuple-of-tuples) matching PET-4's pattern. The runtime `_scanners` list can remain mutable since it holds scanner instances.

### F-5: `reset()` method is a silent spec addition not authorized by the brief
**Severity:** P3
**Where:** spec lines 145-150 (D3b)
**Convention violated:** Silent additions -- spec adds a public method not in the brief's "Done when" criteria or decision list
**Evidence:** The brief (`docs/briefs/PET-3-llmguardscanner-brief.md`) does not mention `reset()`. The spec adds it in D3b with rationale ("allows intentional re-attempts, e.g., after installing the missing package"). The rationale is sound and the method is useful, but per the conventions lens this is a (c)-class addition: spec-level addition with rationale. PET-4 has no equivalent `reset()` method, making this a unilateral API surface expansion.
**Suggested fix:** No change needed -- the rationale is adequate. Noting it here for the human drift-check. Consider whether PET-4 should also have `reset()` for cross-wrapper consistency.

### F-6: Integration test skip mechanism differs from PET-4
**Severity:** P3
**Where:** spec line 263 ("skip via `pytest.importorskip`") vs PET-4 spec line 400 ("@pytest.mark.skipif(not _has_llamafirewall, ...)")
**Convention violated:** Cross-spec consistency for sibling test files
**Evidence:** PET-3 uses `pytest.importorskip("llm_guard")` (a function-level skip). PET-4 uses `@pytest.mark.skipif(not _has_llamafirewall, ...)` with a module-level boolean (a decorator-level skip). Both work but they produce different skip messages and different skip granularity. `pytest.importorskip` is typically called per-test or per-module; `@pytest.mark.skipif` is typically applied per-test or per-class. The inconsistency means test output reads differently across the two scanner test files.
**Suggested fix:** Pick one pattern for all scanner wrapper test files. `pytest.importorskip` at the top of the integration tests section (or as a fixture) is more idiomatic for "skip if extra not installed." Add a note that PET-4/PET-5 should use the same mechanism.

### F-7: `ban_topics` parameter accepted silently without `enable_ban_topics=True`
**Severity:** P3
**Where:** spec line 257 (test 10)
**Convention violated:** Principle of least surprise / "unused argument is suspicious" heuristic
**Evidence:** Spec test 10 (line 257): "passing `ban_topics=["violence"]` without `enable_ban_topics=True` does not activate BanTopics." This is a deliberate design choice documented by the test, but it means a user who writes `LlmGuardScanner(ban_topics=["violence"])` thinking they've enabled topic banning gets silently ignored. The inverse case (spec lines 98-101: `enable_ban_topics=True` without `ban_topics`) correctly raises `ValueError`. The asymmetry could be a source of user confusion.
**Suggested fix:** Consider emitting a `UserWarning` when `ban_topics` is non-None but `enable_ban_topics` is False, or note this as a deliberate design choice in the class docstring. Not load-bearing -- P3 advisory.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 4 | P4: 0

STATUS: GREEN
