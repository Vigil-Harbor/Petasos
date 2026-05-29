# PET-6 Spec Review — Edge Cases (Round 3)

## Closure of round 2 findings

All P1 findings CLOSED. All P2 findings CLOSED or acknowledged in Deferred section.

## Findings

### F-1 (P2): Anonymize ImportError guard mode-dependent
For "replace"/"mask" modes, anonymization succeeds without Presidio installed (manual string path). ImportError only applies to "redact"/"hash" modes.

### F-2 (P2): `asyncio.gather` with `return_exceptions=True` silently captures BaseException
D1 says `gather(return_exceptions=True)` but `_scan_one` catches Exception. With return_exceptions=True, if a scanner raises SystemExit (not caught by _scan_one), gather captures it as a return value rather than propagating — contradicts the BaseException-must-propagate invariant.
**Fix:** Use `gather(*tasks)` without `return_exceptions=True` since _scan_one already converts Exception to ScanResult.

### F-3 (P2): Zero-length position ranges could shadow substantive findings
A finding with Position(5,5) could win over a substantive finding at [4,6].

### F-4 (P2): from_dict() with wrong types does not specify behavior
Non-string Literal fields, non-bool primitive fields pass construction unchecked.

### F-5 (P3): deepcopy with scanner thread locks
Scanner instances not deepcopied (correct) but proximity is a maintenance hazard.

### F-6 (P3): 30s timeout not configurable
### F-7 (P3): pii_entities as list vs tuple from JSON
### F-8 (P3): Non-string input returns safe=False instead of raising

## Summary

P0: 0 | P1: 0 | P2: 4 | P3: 4

STATUS: GREEN
