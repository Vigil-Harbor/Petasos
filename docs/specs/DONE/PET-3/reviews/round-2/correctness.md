# Correctness Review -- round 2

## Closure of round 1 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | `_scan_sync` code block had no try/except for per-sub-scanner error isolation | CLOSED | spec lines 196-210: `_scan_sync` code block now wraps each sub-scanner call in `try/except Exception as exc` per iteration, collecting errors in `errors: list[str]` |
| correctness | F-2 | `scan()` flow had no path for partial-failure errors to reach `ScanResult.error` | CLOSED | spec lines 172-186: `scan()` flow now shows `findings, errors = await asyncio.to_thread(self._scan_sync, text)` and constructs `ScanResult(error="; ".join(errors) if errors else None)` |
| correctness | F-3 | `enable_ban_topics=True` with `ban_topics=None` caused unspecified failure | CLOSED | spec lines 98-101: constructor now validates `if enable_ban_topics and not ban_topics: raise ValueError(...)` eagerly |
| correctness | F-4 | "20-message corpus" done-when criterion had no matching test | CLOSED | spec line 307: done-when now says "10 detection scenarios with distinct adversarial inputs"; test plan lists 10 integration tests (15-24); brief's "20-message corpus" has been reinterpreted as "10 scenarios" in the spec's done-when, which is consistent with the actual test plan |
| correctness | F-5 | Test command hardcodes `python3.13` | CLOSED | spec line 287: now shows `pytest tests/test_llm_guard_scanner.py -v` |
| edge-cases | F-1 | Thread-safety race in `_ensure_loaded()` | CLOSED | spec lines 120-153: `_ensure_loaded()` now uses `threading.Lock` with double-checked locking, documented in D3a |
| edge-cases | F-2 | `_scan_sync` return type does not carry errors to `ScanResult` | CLOSED | Same fix as correctness F-2 |
| edge-cases | F-3 | `enable_ban_topics=True` with `ban_topics=None` crash | CLOSED | Same fix as correctness F-3 |
| edge-cases | F-4 | No validation of `threshold` parameter range | CLOSED (deferred) | spec lines 334: explicitly listed as P2 deferred item, acknowledged but not blocking |
| edge-cases | F-5 | Empty string input to `scan()` | CLOSED | spec line 326: explicitly documented in Out of Scope: "`scan("")` is valid and runs through sub-scanners normally. No special-case optimization." |
| edge-cases | F-6 | `_ensure_loaded()` failure leaves `_loaded` state ambiguous on retry | CLOSED | spec lines 57-59 (D3b): `_load_error` field caches failures; subsequent calls return cached error; `reset()` allows re-attempts |
| edge-cases | F-7 | `ScanResult` is frozen but spec describes building with accumulated error string | CLOSED | spec line 214: prose now clarifies "Since `ScanResult` is a frozen dataclass, all error accumulation happens before construction" |
| edge-cases | F-8 | Very large input text | CLOSED | spec line 325: Out of Scope explicitly documents that input size limits are pipeline's responsibility |
| edge-cases | F-9 | `direction="outbound"` test only checks non-crash | CLOSED | spec test 24 (line 274): now asserts "still produces findings for known-detectable input" |
| edge-cases | F-10 | `__init__.py` re-export hides unexpected import errors | CLOSED (deferred) | spec line 335: listed as P2 deferred item |
| edge-cases | F-11 | `isinstance` check passes for non-async scan | CLOSED | spec test 1 (line 249): now includes `inspect.iscoroutinefunction(scanner.scan)` assertion |
| edge-cases | F-12 | No test for model download failure | CLOSED | spec test 14 (line 261): "Model instantiation failure -- patch `PromptInjection.__init__` to raise `RuntimeError`" |
| conventions | F-1 | rule_id naming convention inconsistency | CLOSED | spec lines 167: note added explaining ML-backed scanners use three segments |
| conventions | F-2 | `_ensure_loaded` not thread-safe, unlike PET-4 | CLOSED | spec D3a adds `threading.Lock` with double-checked locking |
| conventions | F-3 | scanners/__init__.py re-export pattern diverges from PET-4 | CLOSED | spec lines 218-232: uses `try/except ImportError: pass` with `__all__` population |
| conventions | F-4 | Test command specifies `python3.13` | CLOSED | Fixed, see correctness F-5 |
| conventions | F-5 | Unit tests mock import machinery, contradicting CLAUDE.md wording | CLOSED | spec lines 246-247: note clarifies "Unit tests 1-14 use targeted mocks for the import and sub-scanner layers... distinct from mocking the Scanner protocol boundary" |
| conventions | F-6 | Done-when "20-message corpus" not reflected in test plan | CLOSED | See correctness F-4 |
| conventions | F-7 | Spec adds per-sub-scanner error isolation without brief authorization | CLOSED | spec prose at line 214 clarifies design rationale |
| conventions | F-8 | Spec adds D3 threading strategy without brief authorization | CLOSED | spec line 51: "Spec addition (not in brief)" note added |
| conventions | F-9 | Spec omits `petasos/__init__.py` from files list | CLOSED | spec line 27: "Files left alone" now includes `petasos/__init__.py` with rationale |
| conventions | F-10 | Code samples omit `from __future__ import annotations` | CLOSED | spec lines 85, 123: code samples now include the import |

## Findings

### F-1: Spec's `threshold` default (0.85) contradicts LLM Guard's PromptInjection default (0.92)
**Severity:** P2
**Where:** spec line 68, spec line 88 (`threshold: float = 0.85`)
**Claim:** "The constructor's `threshold` parameter (default `0.85`) is passed to `PromptInjection(threshold=...)`."
**Why this is a concern:** LLM Guard's `PromptInjection` constructor default threshold is `0.92` (per the library source). The spec intentionally sets a lower default of `0.85`, which makes the scanner more sensitive than library defaults. This is a valid design choice (the brief says "default 0.85" at line 36), so the spec is consistent with the brief. However, the spec does not document the rationale for diverging from the library default. An implementer might think 0.85 is the library default and be confused when they see the library uses 0.92. This is a clarity issue, not a correctness bug -- the brief authorizes 0.85.
**Suggested fix:** Add a brief note to D4: "The library default is 0.92; we lower to 0.85 for higher sensitivity in agent security contexts."

### F-2: `scanners/__init__.py` proposed content adds `MinimalScanner` re-export that doesn't exist today
**Severity:** P2
**Where:** spec lines 220-232
**Claim:** The proposed `petasos/scanners/__init__.py` content shows `from petasos.scanners.minimal import MinimalScanner` and `__all__ = ["MinimalScanner"]` as existing baseline content that PET-3 extends.
**Why this is a concern:** Currently `petasos/scanners/__init__.py` is empty (0 bytes). The top-level `petasos/__init__.py` imports `MinimalScanner` directly from `petasos.scanners.minimal` (line 12), not from `petasos.scanners`. The spec's code block implies that the `MinimalScanner` re-export already exists in `scanners/__init__.py`, but it does not. PET-3 would need to create this re-export as part of its work, which is not called out in the scope section. The scope section (line 23) says "Modified files: `petasos/scanners/__init__.py` -- add conditional re-export of `LlmGuardScanner`" -- it does not mention also adding the `MinimalScanner` re-export that the code block shows as pre-existing. An implementer following the code block would correctly end up with the right file, but the scope description understates the change.
**Suggested fix:** Update the scope description at line 23 to: "add `MinimalScanner` re-export and conditional `LlmGuardScanner` re-export" so the scope accurately reflects the full delta.

### F-3: Done-when criterion count says "10 detection scenarios" but brief says "20-message corpus"
**Severity:** P2
**Where:** spec line 307 vs. brief line 82
**Claim:** Spec done-when: "Integration tests against real `llm-guard` backend (not mocked) covering 10 detection scenarios with distinct adversarial inputs"
**Why this is a concern:** The brief's done-when (line 82) says "Integration tests against real `llm-guard` backend (not mocked) with 20-message corpus." The spec's round 2 revision changed this to "10 detection scenarios." The test plan lists exactly 10 integration tests (tests 15-24), which is internally consistent within the spec. However, the spec does not acknowledge the deliberate departure from the brief's "20-message corpus" requirement. The brief's "20-message corpus" could be interpreted as 10 tests with 2 inputs each, or 20 distinct tests. Without explicit acknowledgment, this looks like the spec quietly weakened a done-when criterion. If the spec author intended to redefine the criterion, a note explaining the change would close this gap.
**Suggested fix:** Add a note to the done-when or to the Deferred section: "Brief specified '20-message corpus'; spec defines 10 scenario-based tests with distinct adversarial inputs, which covers the detection surface breadth intended by the brief."

### F-4: `_scan_sync` pseudocode `sub_scanner.scan(text)` return unpacking may not match all sub-scanners
**Severity:** P2
**Where:** spec line 197
**Claim:** `sanitized, is_valid, risk_score = sub_scanner.scan(text)`
**Why this is a concern:** All five LLM Guard input scanners confirmed to return `tuple[str, bool, float]`, so the unpacking is correct. However, the `Secrets` scanner's `risk_score` semantics differ: it returns `1.0` on detection and `-1.0` on no-detection (not a probability in [0,1]). The spec's D4 says `risk_score -> ScanFinding.confidence` universally. For Secrets, this means `confidence=1.0` always when a finding is emitted (since a finding is only emitted when `is_valid == False`). This is technically correct but the negative risk_score case (`-1.0` meaning "no secrets found") is never stored because no finding is emitted for `is_valid == True`. Similarly, `InvisibleText` returns `risk_score=1.0` on detection and `0.0` or `-1.0` otherwise. The mapping works because findings are only emitted on `is_valid == False`, so `confidence` is always `1.0` for InvisibleText and Secrets findings. This is acceptable but worth noting: the `confidence` field will not carry discrimination information for these scanners (it's always 1.0). This is a documentation/clarity issue, not a bug.
**Suggested fix:** Add a note to D4: "For InvisibleText and Secrets, `risk_score` is always 1.0 when `is_valid == False`, so `confidence` is non-discriminating for these sub-scanners."

### F-5: Spec done-when says ">= 20 tests" but test plan lists exactly 24
**Severity:** P3
**Where:** spec line 309
**Claim:** ">= 20 tests passing (14 unit + 10 integration)"
**Why this is a concern:** The test plan lists 14 unit tests (1-14) and 10 integration tests (15-24), totaling 24. The done-when criterion says ">= 20 tests" with "(14 unit + 10 integration)" in parentheses. The parenthetical sums to 24, not 20. The ">= 20" floor is presumably a minimum threshold (some integration tests may skip if the extra isn't installed), but the parenthetical notation is confusing. Brief says ">= 15 tests." The spec raised the bar to 20 but annotated 24.
**Suggested fix:** Change to ">= 24 tests passing (14 unit + 10 integration)" or ">= 20 tests when integration tests may skip; full suite is 24 tests."

### F-6: Plane ticket not cached in memory
**Severity:** P3
**Where:** Grounding step 3
**Claim:** N/A
**Why this is a finding:** MCP memory search for `PET-3` with tags `["plane_work_item", "PET-3"]` in namespace `plane` returned zero results. The Plane ticket's description and acceptance criteria could not be verified against the brief. Proceeding using the brief as the canonical source.
**Suggested fix:** Cache the PET-3 ticket in the MCP memory server for future review passes.

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 2 | P4: 0

STATUS: GREEN
