# Edge-Cases Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Spec falsely claims audit.py automatically consumes GuardResult.findings
**Severity:** P1
Spec line 29 says "audit already consumes GuardResult.findings, so findings from exempt param scans flow into the audit trail automatically." This is false — `AuditEmitter.emit()` accepts `PipelineResult`, not `GuardResult`. The guard is an external construct; its findings never enter the audit trail unless the consumer logs them independently. Done-when L421 ("Audit events include findings from exempt tool param scans") is therefore unachievable without additional audit.py changes.
**Suggested fix:** Remove the false audit claim from "Files unchanged"; reword Done-when to clarify that findings are available on `GuardResult` for consumer-side logging, not automatically audited.

### F-2: Test #4 mock type annotation mismatch
**Severity:** P4 (downgraded from P2)
Mock `_boom` returns `None` while `inspect` returns `PipelineResult`. Works through `_scan_params` catch-all; matches existing test patterns.

### F-3: Case-insensitive bypass of built-in name guard
**Severity:** P2
`register("General", ...)` bypasses the check. Already explicitly deferred in spec's Deferred section with sound rationale.

### F-4: No test for profile=None with exempt_param_scan=True
**Severity:** P3
When profile is None, the exempt branch is never reached. Correct but untested.

### F-5: _guard helper does not forward exempt_param_scan
**Severity:** P3
New tests construct ToolCallGuard directly, which is correct. Helper could optionally be extended.

### F-6: Existing GUARD-03 test assertion not affected
**Severity:** P3
test_alias_exec_to_read_exempt_blocked assertion still passes — alias defense prevents exempt path.

### F-7: No concurrent exempt param scan test
**Severity:** P3
Existing concurrency test covers non-exempt tools. Exempt path is stateless, low risk.

### F-8: _BUILTIN_NAMES imported as private constant in tests
**Severity:** P4
Matches existing test conventions.

## Summary
P0: 0 | P1: 1 | P2: 1 | P3: 4 | P4: 2

STATUS: RED P0=0 P1=1 P2=1 P3=4 P4=2
