# Correctness Review -- round 3

## Closure of round 2 findings

| Lens | ID | Title | Status | Evidence |
|---|---|---|---|---|
| correctness | F-1 | `threshold` default 0.85 vs LLM Guard 0.92 | CLOSED (P2 retained) | Spec line 68 still uses 0.85, consistent with brief line 36. Clarity note remains absent but this is P2 advisory, not blocking |
| correctness | F-2 | `scanners/__init__.py` MinimalScanner re-export not in scope description | CLOSED (P2 retained) | Spec line 23 still says only "add conditional re-export of LlmGuardScanner" but code block at lines 229-237 correctly shows both. Scope description understates the change, but implementer following the code block gets the right file |
| correctness | F-3 | Done-when "10 detection scenarios" vs brief "20-message corpus" | CLOSED (P2 retained) | Spec line 307 says "10 detection scenarios"; test plan lists 10 integration tests (15-24). Brief departure is unacknowledged but internally consistent |
| correctness | F-4 | `_scan_sync` Secrets scanner risk_score semantics | CLOSED (P2 retained) | Spec line 64-66 mapping is technically correct; confidence is always 1.0 for InvisibleText/Secrets findings. Clarity improvement not adopted but P2 advisory |
| correctness | F-5 | Done-when ">= 20" vs test plan total of 24 | CLOSED (P3 retained) | Spec line 312: ">= 20 tests passing (14 unit + 10 integration)" unchanged. Parenthetical sums to 24. Minor wording inconsistency, P3 |
| correctness | F-6 | Plane ticket not cached in memory | CLOSED (P3 retained) | MCP memory search for PET-3 still returns zero results. Proceeding with brief |
| edge-cases | F-1 | `_ensure_loaded()` double-checked locking missing `_load_error` inside lock | CLOSED | Spec lines 138-139: `if self._load_error is not None: return` now present inside `with self._lock:` block with comment "another thread failed while we waited for the lock" |
| edge-cases | F-2 | `reset()` concurrent with `scan()` causes silent false-negative | CLOSED | Spec lines 148-154: `reset()` docstring now documents caller-responsibility contract; D3b line 59 adds safety contract sentence |
| edge-cases | F-3 | `_load_error` check in `scan()` redundant with `_ensure_loaded()` | CLOSED (deferred) | Spec Deferred line 346: explicitly listed as P2 with rationale |
| edge-cases | F-4 | `_scan_sync` does not snapshot `_scanners` reference | CLOSED (deferred) | Spec Deferred line 347: explicitly listed as P2, mitigated by `reset()` caller-responsibility contract |
| edge-cases | F-5 | `ban_topics` constructor validation does not check element types | CLOSED (deferred) | Spec Deferred line 348: explicitly listed as P2 with concrete future improvement noted |
| edge-cases | F-6 | Test 12 may not reliably detect the race | CLOSED (P3 retained) | P3 advisory, no spec change required |
| edge-cases | F-7 | `_scan_sync` exception handler swallows exception type information | CLOSED (P3 retained) | P3 advisory, no spec change required |
| edge-cases | F-8 | No test for `reset()` followed by successful re-load | CLOSED (P3 retained) | P3 advisory, no spec change required |
| conventions | F-1 | PET-3 and PET-4 disagree on `__init__.py` top-level re-export | CLOSED (P2 retained) | Cross-spec consistency issue; PET-3 spec line 27 is a deliberate choice. Alignment is PET-4's concern |
| conventions | F-2 | PET-3 and PET-4 use incompatible `scanners/__init__.py` re-export patterns | CLOSED (P2 retained) | PET-3's `try/except ImportError` with `__all__.append` pattern is correct; PET-4 should adopt it. Cross-spec issue, not a PET-3 spec defect |
| conventions | F-3 | `_ensure_loaded` double-state vs PET-4 single-state pattern | CLOSED (P2 retained) | Internal consistency verified; PET-3's three-state machine is self-consistent. Pattern divergence is a conventions concern, not correctness |
| conventions | F-4 | Sub-scanner registry uses bare `list[tuple]` not `MappingProxyType` | CLOSED (P3 retained) | P3 advisory about frozen-exports invariant |
| conventions | F-5 | `reset()` is a silent spec addition not in brief | CLOSED (P3 retained) | Rationale adequate; noted for drift-check |
| conventions | F-6 | Integration test skip mechanism differs from PET-4 | CLOSED (P3 retained) | Cross-spec consistency P3 advisory |
| conventions | F-7 | `ban_topics` accepted silently without `enable_ban_topics=True` | CLOSED (P3 retained) | Deliberate design choice documented in test 10 |

## Findings

No findings.

All round 1 findings were closed in round 2. All round 2 findings (across all three lenses) have been either directly addressed in the current spec revision (edge-cases P1s resolved with code and docstring changes) or remain as correctly-categorized P2/P3 advisories that do not block shipping. The spec's internal cross-references are consistent: function signatures in the class structure section match the scan() flow pseudocode, `_scan_sync` return type matches how `scan()` unpacks it, `ScanFinding` and `ScanResult` constructions match `_types.py` definitions, and all file references are accurate against current code on disk. No new issues were introduced by the round 2 revisions.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 0 | P4: 0

STATUS: GREEN
