# Edge-Cases Review -- round 1

## Findings

### F-1: `recent_sessions` NameError after cross-session tracker replacement
**Severity:** P1
Spec replaces L301-304 but alert construction at L312,316 still references `recent_sessions` which is no longer defined. NameError at runtime when burst threshold is met.

### F-2: Tracker cap can silently prevent cross-session burst detection
**Severity:** P1
If `2 * ring_buffer_capacity < burst_count`, the tracker cap prevents the burst from ever firing. E.g., `capacity=5, burst_count=15` → cap=10 < 15.

### F-3: `_last_callback_error` cleared after sequence increment, not at top of emit()
**Severity:** P2
D2 says "cleared at the top" but code places clearing just before callback block.

### F-4: No test for SystemExit or CancelledError in callback
**Severity:** P2
D1 explicitly names these but tests only cover RuntimeError, KeyboardInterrupt, ValueError.

### F-5: Pipeline accesses private `_last_callback_error` and `_callback_errors` across class boundaries
**Severity:** P2
Pipeline reaches into private attributes of AuditEmitter and AlertManager.

### F-6: Concurrent inspect() sharing _callback_errors — design assumption undocumented
**Severity:** P3
Safe today (no await between evaluate and read) but fragile under async callbacks.

### F-7: No test for callback=None path with new attributes
**Severity:** P3
Happy path (no callback) not tested with new _last_callback_error attribute.

### F-8: _cross_session_tracker and ring buffer have independent TTLs in _prune_stale()
**Severity:** P3
Tracker uses burst_window; ring buffer uses max(all windows). Minor inconsistency.

## Summary
P0: 0 | P1: 2 | P2: 3 | P3: 3 | P4: 0

STATUS: RED P0=0 P1=2 P2=3 P3=3 P4=0
