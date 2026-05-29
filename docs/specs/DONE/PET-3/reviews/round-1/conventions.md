# Conventions Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: rule_id naming convention inconsistency -- missing sub-category segment
**Severity:** P2
**Where:** spec.md:120-126 (Sub-scanner registry table)
**Convention violated:** MinimalScanner uses four-segment `petasos.syntactic.<category>.<slug>`. LlmGuardScanner uses three-segment `petasos.llmguard.<slug>`. PET-4 and PET-5 also use three segments for ML-backed scanners.
**Suggested fix:** Add note acknowledging the difference: ML-backed scanners use three segments because each sub-scanner maps 1:1 to a single detection class.

### F-2: `_ensure_loaded` is not thread-safe, unlike PET-4
**Severity:** P2
**Where:** spec.md:99-112 (Lazy-load mechanism)
**Convention violated:** PET-4 spec uses `threading.Lock` with double-checked locking in `_ensure_loaded()`.
**Suggested fix:** Add `threading.Lock` double-checked locking to match PET-4 pattern.

### F-3: scanners/__init__.py re-export pattern diverges from PET-4 spec
**Severity:** P2
**Where:** spec.md:162-172
**Convention violated:** PET-4 uses unconditional import with `__all__`; PET-3 uses `try/except ImportError: pass`.
**Suggested fix:** Harmonize pattern across specs. try/except is more robust; add `__all__`.

### F-4: Test command specifies `python3.13`, not project convention
**Severity:** P2
**Where:** spec.md:216
**Convention violated:** CLAUDE.md, pyproject.toml minimum is 3.11.
**Suggested fix:** Change to `pytest tests/test_llm_guard_scanner.py -v`.

### F-5: Unit tests mock import machinery, contradicting CLAUDE.md test policy wording
**Severity:** P2
**Where:** spec.md:183-184
**Convention violated:** CLAUDE.md: "Scanner wrappers use integration tests against real backends, not mocks."
**Suggested fix:** Add note clarifying the boundary: unit tests mock the import/sub-scanner layer, not the Scanner protocol boundary.

### F-6: Done-when "20-message corpus" not reflected in test plan
**Severity:** P3
**Where:** spec.md:233 vs. spec.md:193-205
**Suggested fix:** Align done-when with actual test plan.

### F-7: Spec adds per-sub-scanner error isolation without brief authorization
**Severity:** P3
**Where:** spec.md:159, spec.md:188
**Suggested fix:** Add note: "Spec addition (not in brief): per-sub-scanner error isolation."

### F-8: Spec adds D3 threading strategy without brief authorization
**Severity:** P3
**Where:** spec.md:48
**Suggested fix:** None needed -- rationale is adequate.

### F-9: Spec omits `petasos/__init__.py` from modified files
**Severity:** P3
**Where:** spec.md:23
**Suggested fix:** Add to "Files left alone" with rationale, or add to "Modified files" if top-level re-export is intended.

### F-10: Code samples omit `from __future__ import annotations`
**Severity:** P4
**Where:** spec.md:74, 102, 131
**Suggested fix:** Add to class structure code sample.

## Summary
P0: 0 | P1: 0 | P2: 5 | P3: 4 | P4: 1

STATUS: GREEN
