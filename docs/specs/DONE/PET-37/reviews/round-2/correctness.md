# Correctness Review -- round 2

## Closure of round 1 findings

All round 1 findings CLOSED:
- F-1 (P2): spec D1 line 36 now says "The consumer constructs the guard"
- F-2 (P3): Constructor "Before" block omission — minor, accepted
- F-3 (P3): Test #3 param changed to `{"count": "42"}`

## Findings

### F-1: Brief Done-when audit criterion reinterpreted without explicit Decision section
**Severity:** P2
Brief says "Audit events include findings from exempt tool param scans." Spec reinterprets as consumer-side logging. The reinterpretation is correct but documented only in "Files unchanged" (L29), not as a formal Decision.
**Suggested fix:** Optionally elevate to a Decision D5 with cross-reference from Done-when.

### F-2: Line 28 still says "the pipeline calls ToolCallGuard.evaluate()"
**Severity:** P2
The consumer calls evaluate(), not the pipeline. The conclusion (pipeline.py unchanged) is correct but the reason is wrong.
**Suggested fix:** Replace with "the consumer calls ToolCallGuard.evaluate(), which internally calls Pipeline.inspect()"

### F-3: Test #1 vs Test #3 opposite expectations for findings
**Severity:** P3
Both assertions are correct but the spec could clarify that Test #3's clean params still traverse _scan_params.

## Summary
P0: 0 | P1: 0 | P2: 2 | P3: 1 | P4: 0

STATUS: GREEN
