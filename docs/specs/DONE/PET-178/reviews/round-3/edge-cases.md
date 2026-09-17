# Edge-Cases Review — round 3

## Closure of round 2 findings
All round-2 P0/P1 CLOSED as in the author's closure_manifest. D-1–D-5 well-formed. Those roots not re-filed.

## Findings

### F-1: PII-only above the ceiling can still pass through with no banner
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec.md:161 (§ Coverage regimes); spec.md:256 (§ Banner ceiling-clean path); spec.md:293 (§ Test plan clean-truncated rewrite)
**Suggested fix:** Qualify the PET-112 sentence: PII-only still does not take the findings path and still emits no `ingest_flagged`; above ceiling it takes `path="ceiling"` so the remainder is not claimed verified. Add `test_pii_only_above_ceiling_still_gets_the_ceiling_banner` (`len=1_000_001`, HIGH PII, no injection): banner present, line 1 has no `prompt-injection`, `Coverage: ceiling.` / `Scanned 1000000 of 1000001`, no `ingest_flagged`. Keep the short-content PII-only pin as `None`.

## Summary
P0: 0 | P1: 0 | P2: 1 | P3: 0 | P4: 0

STATUS: GREEN
