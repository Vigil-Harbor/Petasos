# PET-6 Spec Review — Edge Cases (Round 2)

## Closure of round 1 findings

All P1 findings from round 1 are CLOSED (BaseException→Exception, anonymization text match, sweep algorithm clarity). See closure table in correctness round 2 for cross-lens closures.

## Findings

### F-1 (P2): Empty text — ML scanners invoked with empty string
**Section:** Design §4.2
`pipeline.inspect("")` would invoke ML scanners with `normalized_text = ""`. Some ML models raise on empty input. Test plan covers it but design doesn't specify early return.
**Fix:** Add empty-string early return before ML fan-out.

### F-2 (P1): NormalizedText field name `.has_rtl_override` does not exist
**Section:** Design §4.2, stage 1
Same as correctness F-1. Actual field is `.rtl_overrides_detected`.

### F-3 (P2): MinimalScanner detection mechanism unspecified
**Section:** Design §4.2 constructor (line 139)
"the first MinimalScanner found" — by `isinstance` or by `scanner.name == "minimal"`? Different behavior for custom scanners.

### F-4 (P2): "Double tie → keep both" ambiguous in running-winner sweep
**Section:** Design §4.3
The sweep tracks one `current`. "Keep both" has no mechanism in a single-variable sweep.
**Fix:** Clarify: "On double tie: emit `current` to output, set `current = next`."

### F-5 (P2): `scanner.name` access in error handler may itself raise
**Section:** Design §4.2, _scan_one (line 159)
If `scanner.name` raises, the error ScanResult can't be constructed.
**Fix:** Capture `scanner.name` into a local before the try block.

### F-6 (P2): Anonymize call not wrapped in ImportError guard
**Section:** Design §4.5
`petasos.scanners.presidio.anonymize()` has internal imports that fail when Presidio isn't installed. Pipeline must wrap in try/except ImportError.

### F-7 (P3): from_dict type coercion not specified
### F-8 (P2): MinimalScanner error not reflected in fail-mode
MinimalScanner can error at runtime. In closed/degraded modes, loss of the syntactic baseline should set safe=False.

### F-9 (P3): deepcopy on frozen dataclass is redundant but harmless
### F-10 (P3): Zero-width position overlap predicate

## Summary

| Severity | Count |
|----------|-------|
| P0 | 0 |
| P1 | 1 |
| P2 | 6 |
| P3 | 3 |

STATUS: RED P0=0 P1=1 P2=6 P3=3
