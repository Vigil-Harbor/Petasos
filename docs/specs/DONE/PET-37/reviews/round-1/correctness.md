# Correctness Review -- round 1

## Closure of round 0 findings
N/A -- round 1

## Findings

### F-1: Inaccurate rationale claim that pipeline constructs the guard
**Severity:** P2
The spec says "The pipeline constructs the guard, so it can pass the parameter." In reality, `petasos/pipeline.py` does not instantiate `ToolCallGuard` — the consumer constructs the guard and passes the pipeline in. The design decision is sound; only the justification sentence is inaccurate.
**Suggested fix:** Replace with "The consumer constructs the guard, so it can pass the parameter at construction time."

### F-2: Spec's constructor code block omits "Before" pattern
**Severity:** P3
The spec shows the constructor with the new parameter but does not include a "Before"/"After" pair, unlike Step 4 and the profiles changes.

### F-3: Test #3 assertion depends on scanner not matching file paths
**Severity:** P3
`{"path": "/home/user/doc.txt"}` is unlikely to trigger rules today, but could break if future rules detect path traversal. Consider using a less fragile param like `{"count": "42"}`.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 2 | P4: 0

STATUS: GREEN
