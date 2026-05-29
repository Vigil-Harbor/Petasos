# PET-4 Spec Review — Edge Cases (Round 3)

**Spec:** `docs/specs/TODO/PET-4.spec.md` (v3)
**Brief:** `docs/briefs/PET-4-llamafirewallscanner-brief.md`
**Round:** 3

---

## Closure of round 2 findings

| Finding | Status | Evidence |
|---------|--------|---------|
| R2 F-1 (P1) `_loaded = True` before try; partial init memory leak | CLOSED | `_components.clear()` in both except handlers, fail-once semantics documented |
| R2 F-2 (P1) `assert` stripped under `-O` | CLOSED | Replaced with explicit `if` guard returning error tuple |
| R2 F-3 (P2) No `direction` validation | CLOSED | Matches MinimalScanner pattern, mypy-enforced |
| R2 F-4 (P2) `result.decision` enum repr verbose | CLOSED | Uses `result.decision.name` in fallback message |
| R2 F-5 (P2) Thread pool exhaustion during cold start | CLOSED | Documented in Deferred section |
| R2 F-6 (P2) Partial init `_components` orphaned memory | CLOSED | Addressed by F-1 fix — `_components.clear()` |
| R2 F-7 (P3) `__all__` duplicates on reload | CLOSED | Harmless, acknowledged |
| R2 F-8 (P2) Test 20 under-specified | CLOSED | Now specifies: prompt_guard + code_shield, monkeypatch code_shield, verify partial findings |
| R2 F-9 (P3) PromptGuard input truncation | CLOSED | Documented in Deferred section |

## Findings

### F-1 (P2) — Stale cached message classes after partial init failure

After `_components.clear()` in except handlers, `_user_message_cls`, `_assistant_message_cls`, and `_allow_decision` remain set from the successful `from llamafirewall import ...` line. These are stale references to module-level classes from a library whose initialization failed. In practice harmless because `_components` is empty → `_scan_sync` iterates nothing, but the stale refs consume memory until GC.

### F-2 (P2) — `_allow_decision` not validated in `_scan_sync` guard

The `_scan_sync` guard checks `self._user_message_cls is None or self._assistant_message_cls is None` but does not check `self._allow_decision is None`. If `_ensure_loaded` somehow set message classes but not `_allow_decision` (impossible in current code but defensive gap), the comparison `result.decision != self._allow_decision` would compare against `None`.

### F-3 (P2) — `_ensure_loaded` called on event loop thread before `to_thread`

The `scan()` method calls `_ensure_loaded()` synchronously before dispatching to `asyncio.to_thread()`. On first call, this blocks the event loop during model downloads. Documented in spec section 3 and Deferred. PET-6 scope.

### F-4 (P2) — Constructor does not validate enable flag combinations

No validation that at least one component is enabled. `LlamaFirewallScanner(enable_prompt_guard=False)` is valid (empty scan, no error). Documented in spec section 3 ("valid no-op configuration"). Design is intentional but could surprise users.

### F-5 (P3) — Concurrent scan() during first-call init: thread safety of `_components` iteration

`_scan_sync` iterates `self._components.items()` without holding the lock. During `_ensure_loaded`, components are added one at a time. A concurrent `scan()` call that passes the outer `_loaded` check (after `_loaded = True` is set) could iterate a partially-populated `_components`. In practice, the lock prevents this — the second thread blocks on `with self._lock` and sees the final state. Safe, but the reasoning is subtle.

### F-6 (P3) — Dict iteration safety during `_scan_sync`

`_scan_sync` iterates `self._components.items()`. No concurrent modification is possible (dict is only written during `_ensure_loaded` under lock, never modified after). Safe.

### F-7 (P3) — Fail-once semantics: second call after init failure returns error immediately

After a failed `_ensure_loaded`, `_loaded = True` and `_load_error` is set. Subsequent `scan()` calls return the cached error immediately without retrying. Correct per design intent (fail-once). The error message from the first failure is preserved.

### F-8 (P3) — `result.decision.name` assumes enum has `.name` attribute

LlamaFirewall's `ScanDecision` is a Python enum, so `.name` is guaranteed by the enum protocol. If Meta changes `ScanDecision` to a non-enum type, `.name` would break. Extremely unlikely — enums are idiomatic Python for this pattern.

STATUS: GREEN
