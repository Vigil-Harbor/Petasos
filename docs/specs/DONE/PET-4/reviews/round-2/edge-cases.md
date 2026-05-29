# PET-4 Spec Review — Edge Cases (Round 2)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v2)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 2

---

## Closure of round 1 findings

| Finding | Status | Evidence |
|---------|--------|---------|
| R1 F-1 (P0) Two contradictory _scan_sync designs | CLOSED | Single tuple-return design |
| R1 F-2 (P1) Partial failure findings lost | CLOSED | Tuple-return preserves partial results |
| R1 F-3 (P2) Empty string input | CLOSED | Test 11 added |
| R1 F-4 (P1) No confidence clamping | CLOSED | `max(0.0, min(1.0, raw_score))` |
| R1 F-5 (P2) session_id test | CLOSED | Documented in Deferred |
| R1 F-6 (P1) String comparison fragile | CLOSED | Enum comparison via cached `ScanDecision.ALLOW` |
| R1 F-7 (P1) Lock held during download | CLOSED | Documented in section 3 |
| R1 F-8 (P2) GIL note | CLOSED | Documented in Deferred |
| R1 F-9 (P1) Replacement semantics | CLOSED | Additive `__all__` pattern |
| R1 F-10 (P2) Cache message classes | CLOSED | Cached in `_ensure_loaded` |
| R1 F-11 (P2) MappingProxyType | CLOSED | Applied |
| R1 F-12 (P0) _ComponentErrors undefined | CLOSED | Removed entirely |

## Findings

### F-1 (P1) — `_loaded = True` set before try-block; partial init permanently cached as success

`self._loaded = True` is set before the try block. If `LlamaFirewall()` succeeds for one component but fails for another, `_components` holds partial state. On subsequent calls, `_ensure_loaded()` returns `False` (load error set), but `_components` retains the successful instance — a memory leak.

**Fix:** Keep `_loaded = True` early (fail-once semantics — don't retry broken installs), but clear `self._components` in both `except` handlers to avoid the memory leak.

### F-2 (P1) — `assert` statements in `_scan_sync` stripped under `python -O`

`assert self._user_message_cls is not None` is stripped under `-O`. If `_scan_sync` is reached with `None` classes, the error message is opaque (`'NoneType' object is not callable`).

**Fix:** Replace `assert` with explicit `if` checks returning a descriptive error tuple.

### F-3 (P2) — No `direction` validation; invalid values silently fall through to `else` branch

Matches MinimalScanner pattern. `Direction` is enforced by mypy at the type level.

### F-4 (P2) — `result.decision` enum repr in fallback message may be verbose

Use `result.decision.name` for cleaner output in the fallback message string.

### F-5 (P2) — Thread pool exhaustion during concurrent cold-start `scan()` calls

Threads block on lock during model download, consuming pool slots. Document as known cold-start concern.

### F-6 (P2) — Partial init `_components` holds orphaned model memory

Addressed by F-1 fix — clearing `_components` in except handlers.

### F-7 (P3) — `__all__` additive pattern produces duplicates on `importlib.reload()`

Harmless. Module reload is not a production concern.

### F-8 (P2) — Test 20 under-specified for multi-component partial failure

Should specify: enable prompt_guard + code_shield, monkeypatch code_shield to raise, verify prompt_guard findings preserved alongside error.

### F-9 (P3) — Large input truncation by PromptGuard's internal tokenizer

PromptGuard truncates to ~512 tokens. Pipeline-level `oversized-payload` rule fires first in practice.

STATUS: RED P0=0 P1=2 P2=4 P3=2 P4=0
