# PET-6 Spec Review — Edge Cases (Round 1)

## Findings

### F-1 (P1): BaseException catch in inspect() swallows KeyboardInterrupt/SystemExit
**Severity:** P1
**Section:** Design §4.2
The top-level catch says "catches `BaseException`" — this would swallow `KeyboardInterrupt` and `SystemExit`, preventing clean shutdown. Must catch `Exception` only and let `BaseException` subclasses like `KeyboardInterrupt` and `SystemExit` propagate.

### F-2 (P1): Same BaseException vs Exception inconsistency in _scan_one
**Severity:** P1
**Section:** Decision D1, Design §4.2 stage 4
D1 prose says "catches `BaseException`" but the `_scan_one` code block catches `Exception`. If `_scan_one` catches `BaseException`, a scanner that triggers `KeyboardInterrupt` (e.g., via a buggy C extension) would be silently converted to an error ScanResult. The spec should explicitly use `Exception` in both places and note that `BaseException` subclasses propagate.

### F-3 (P1): Anonymization position offset mismatch
**Severity:** P1
**Section:** Design §4.5
The anonymization section says "The text passed to anonymize is the **original** text (not normalized), because position offsets in PII findings refer to the original input." But if ML scanners receive normalized text (per the fix needed for F-2 in correctness), then PII findings from PresidioScanner will have positions relative to the **normalized** text. The anonymize call must use the same text that generated the findings — either both normalized or both original. Since MinimalScanner normalizes internally and its positions refer to its own internal normalized text, the spec must clarify which text's positions are canonical and what text is passed to anonymize.

### F-4 (P1): Finding merge sweep algorithm description is ambiguous
**Severity:** P1
**Section:** Design §4.3
"for each pair of adjacent positioned findings, if ranges overlap" — does "adjacent" mean adjacent in the sorted list (sweep line), or adjacent in text position? A sweep algorithm compares each finding against the current active set, not just the immediately preceding one. E.g., three findings at [0,10], [5,15], [8,20] — the third overlaps the first but isn't adjacent to it in the sorted list. The algorithm description should be a clearer sweep: maintain a running "current winner" and compare each new finding against it.

### F-5 (P2): Empty text input not addressed
**Severity:** P2
**Section:** Design §4.2
What happens with `pipeline.inspect("")`? MinimalScanner presumably returns no findings, but does normalization handle empty string? The test plan has "Empty string input → valid PipelineResult with safe=True" but the design doesn't address it.

### F-6 (P2): Unicode surrogate pairs in positions
**Severity:** P2
**Section:** Design §4.3
Python str positions count by code points, but some scanners (especially those wrapping C/Rust libraries) may count by bytes or UTF-16 code units. The spec assumes all position values are in Python str offsets. Should note this assumption explicitly.

### F-7 (P2): Concurrent modification of scanner state
**Severity:** P2
**Section:** Design §4.2, stage 4
If a scanner has internal mutable state (e.g., PresidioScanner's lazy-loaded analyzer), concurrent calls via `asyncio.gather` are safe only because asyncio is single-threaded. But `asyncio.to_thread` (used by PresidioScanner internally) creates real thread concurrency. The spec should note that scanners are responsible for their own thread safety.

### F-8 (P3): No cap on number of findings
**Severity:** P3
**Section:** Design §4.3
A pathological input could produce thousands of findings. No practical concern at current scale (brief says <50 findings per scan), but no explicit cap.

### F-9 (P2): `wait_for` cancellation semantics
**Severity:** P2
**Section:** Design §4.2, stage 4
`asyncio.wait_for` cancels the underlying task on timeout. If a scanner is doing cleanup in a finally block (e.g., releasing a model resource), cancellation could interrupt it. The spec should acknowledge this.

### F-10 (P2): No test for direction="outbound"
**Severity:** P2
**Section:** Test plan
The test plan tests direction override and default but doesn't explicitly test `direction="outbound"` path.

### F-11 (P3): Pipeline with zero scanners and no MinimalScanner
**Severity:** P3
**Section:** Design §4.2
The constructor "separates scanners into _minimal_scanner (the first MinimalScanner found, or a fresh one if none provided)". What if someone subclasses MinimalScanner — does `isinstance` check work? The protocol-based design doesn't guarantee type-checking by class.

### F-12 (P3): Hash key security
**Severity:** P3
**Section:** Design §4.5
The hash_key is stored in config as a plain string. In a frozen dataclass, it's still readable. Not a PET-6 concern but worth noting.

### F-13 (P3): Race between config deepcopy and scanner references
**Severity:** P3
**Section:** Design, D6
The pipeline deepcopies config but scanners are stored by reference. If a caller mutates a scanner's internal state after pipeline construction (e.g., changing `score_threshold`), the pipeline sees the change. The spec says scanners are separated from config (D7) but doesn't address scanner mutability.

## Summary

| Severity | Count |
|----------|-------|
| P0 | 0 |
| P1 | 4 |
| P2 | 5 |
| P3 | 4 |

STATUS: RED P0=0 P1=4 P2=5 P3=4
