# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: `premium_features` dict mutable on frozen PipelineResult
**Severity:** P1
**Where:** spec section 5.5
**Edge case:** Caller mutates `result.premium_features["frequency"] = "hacked"`.
**Suggested fix:** Use `types.MappingProxyType` or document immutability contract.

### F-2: PipelineResult rebuild at stage 12 drops premium fields
**Severity:** P1
**Where:** spec section 5.4
**Suggested fix:** Both construction sites must include premium fields. (Duplicate of correctness F-2.)

### F-3: Dict mutation during iteration in eviction loop
**Severity:** P2
**Where:** spec section 5.1 step 1
**Edge case:** Deleting from `self._sessions` while iterating raises `RuntimeError` in Python.
**Suggested fix:** Collect stale IDs first, then delete in second pass.

### F-4: `_creation_timestamps` deque never pruned -- unbounded growth
**Severity:** P1
**Where:** spec section 5.1
**Suggested fix:** Prune entries older than 60 seconds during rate-limit check (matching Drawbridge).

### F-5: DISABLED_RESULT and RATE_LIMITED_RESULT identical -- caller can't distinguish
**Severity:** P2
**Suggested fix:** Use object identity (`result is RATE_LIMITED_RESULT`) and document it.

### F-6: Escalation hook imports evaluate_tier but never calls it
**Severity:** P2
**Suggested fix:** Remove dead import. (Duplicate of correctness F-3.)

### F-7: Frozen dataclass needs object.__setattr__ for frequency_weights
**Severity:** P1
**Suggested fix:** Show the pattern. (Duplicate of correctness F-10.)

### F-8: frequency_weights glob key convention (".*" suffix) leaky abstraction
**Severity:** P2
**Suggested fix:** Document that ".*" suffix is semantically meaningful.

### F-9: Empty finding_types acts as decay heartbeat -- intentional but undocumented
**Severity:** P3
**Suggested fix:** Add one-line note.

### F-10: Tier 3 termination doesn't force safe=False
**Severity:** P1
**Where:** spec section 5.4
**Edge case:** Tier 3 terminated session can still yield safe=True if message has no HIGH/CRITICAL findings.
**Suggested fix:** Explicitly state that `safe` is independent of escalation tier and document this.

### F-11: FrequencyTracker always constructed even in OSS-only installations
**Severity:** P3
**Suggested fix:** Note as acceptable overhead for PET-7.

### F-12: `>=` vs `>` threshold comparison -- spec uses >= but brief uses >
**Severity:** P1
**Where:** spec section 5.2 vs brief lines 38-41
**Suggested fix:** Add decision noting >= matches Drawbridge, overrides brief's >.

### F-13: tier field as bare str -- no type enforcement
**Severity:** P2
**Suggested fix:** Use Literal type or enum.

### F-14: No test for frequency hook error landing in PipelineResult.errors
**Severity:** P2
**Suggested fix:** Add test to test_premium_integration.py.

### F-15: math.exp overflow guard for negative elapsed
**Severity:** P2
**Suggested fix:** Clamp: `elapsed = max(0.0, now - state.last_update)`.

## Summary
P0: 0 | P1: 5 | P2: 5 | P3: 2

STATUS: RED P0=0 P1=5 P2=5 P3=2
