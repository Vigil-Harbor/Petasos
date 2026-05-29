# PET-6 Spec Review — Correctness (Round 1)

## Findings

### F-1 (P1): Double normalization — MinimalScanner normalizes internally
**Severity:** P1
**Section:** Design §4.2, stage 2
The spec says the syntactic pre-filter receives `normalized_text`, but MinimalScanner calls `normalize(text)` internally in `_scan_impl()` (line 150 of `scanners/minimal.py`). Passing pre-normalized text to MinimalScanner means it normalizes twice. The spec must clarify that MinimalScanner receives the **original raw text** (it handles its own normalization).

### F-2 (P1): Ambiguous which text ML scanners receive
**Severity:** P1
**Section:** Design §4.2, stage 4
The fan-out code block shows `scanner.scan(text, ...)` but does not specify whether `text` is the original or normalized text. ML scanners should receive normalized text (they don't normalize internally like MinimalScanner does), but the spec must be explicit.

### F-3 (P0): D1 says `BaseException` but code block catches `Exception`
**Severity:** P0
**Section:** Design §4.2 (top-level catch), Decision D1
The prose in the pipeline-never-throws paragraph says "catches `BaseException`" but the `_scan_one` code block catches `Exception`. These are different — `BaseException` includes `KeyboardInterrupt` and `SystemExit`, which should not be silently swallowed. Must pick one consistently (recommend `Exception`).

### F-4 (P0): Premium hook prose claims `**kwargs` but code blocks lack it
**Severity:** P0
**Section:** Design §4.6
The prose after the premium hook code blocks says "Signatures accept `**kwargs` for forward compatibility" but the actual code blocks in §4.6 do not include `**kwargs` in any signature. Either add `**kwargs` to the code blocks or remove the claim from the prose.

### F-5 (P2): `pii_entities` not wired through to anonymization call
**Severity:** P2
**Section:** Design §4.5
The config has `pii_entities: tuple[str, ...]` but the anonymization call in §4.5 doesn't use it for filtering. The existing `anonymize()` function signature doesn't accept entity filtering either. This is a future concern, not a PET-6 bug, but the spec should acknowledge the gap.

### F-6 (P1): Severity comparison guidance is misleading
**Severity:** P1
**Section:** Design §4.3
The finding merge section says "using `Severity` enum ordering: CRITICAL=0, HIGH=1, etc. or use an explicit rank dict" but the actual Severity enum in `_types.py` has string values (`"critical"`, `"high"`, etc.), not integer values. String-valued enums have no natural ordering in Python. The spec must use an explicit rank dict — the parenthetical "(or use an explicit rank dict)" should be the only approach.

### F-7 (P2): Config direction validation missing
**Severity:** P2
**Section:** Design §4.1
The `__post_init__` validation list doesn't include `direction` — should validate it's one of `"inbound"` or `"outbound"`.

### F-8 (P2): normalize() doesn't support per-step toggles
**Severity:** P2
**Section:** Design §4.2, stage 1
The spec mentions normalization toggles and says "if any normalization toggle is False, skip normalization entirely" but this is a significant behavioral gap — disabling one toggle (e.g., RTL detection) shouldn't disable NFKC normalization. Acknowledged in Out of Scope but the all-or-nothing fallback deserves a comment in the spec.

### F-9 (P3): `asyncio.wait_for` timeout not configurable
**Severity:** P3
**Section:** Design §4.2, stage 4
The 30-second timeout is hardcoded. Could be a config field. Low priority.

### F-10 (P3): No explicit test for `from_dict()` rejecting non-dict input
**Severity:** P3
**Section:** Test plan, test_config.py
Edge case: `from_dict("not a dict")` should raise TypeError.

### F-11 (P2): Aggregate severity mentioned but not used
**Severity:** P2
**Section:** Design §4.3
The merge function "computes aggregate severity (highest severity)" but this value isn't stored anywhere. `PipelineResult` has no `aggregate_severity` field. Either remove the claim or explain where the value is used.

### F-12 (P3): No test for pipeline with duplicate scanner names
**Severity:** P3
**Section:** Test plan
What happens if two scanners have the same `name` property?

## Summary

| Severity | Count |
|----------|-------|
| P0 | 2 |
| P1 | 3 |
| P2 | 4 |
| P3 | 3 |

STATUS: RED P0=2 P1=3 P2=4 P3=3
