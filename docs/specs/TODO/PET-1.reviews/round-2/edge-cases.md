# PET-1 Spec Review — Edge Cases (Round 2)

**Spec:** `docs/specs/TODO/PET-1.spec.md`
**Brief:** `docs/briefs/PET-1-brief.md`
**Round:** 2

---

## Closure of round 1 findings

| Finding | Status | Evidence |
|---------|--------|----------|
| R1/F-1 (RTL_OVERRIDES/INVISIBLE_CHARS inline invisible chars) | CLOSED | Lines 240-280 now use `\uXXXX` escape sequences |
| R1/F-2 (MinimalScanner.scan() no exception guard) | CLOSED | Line 360 prescribes try/except with ScanResult(error=) return |
| R1/F-3 (JSON depth check RecursionError) | CLOSED | Line 402 prescribes iterative approach with RecursionError catch |

---

## Findings

### F-1 [P2] `confusables_normalized` flag semantics diverges from Drawbridge without acknowledgement

Same as correctness R2/F-1. The flag only captures homoglyph mapping changes, not NFKC. Drawbridge captures both.

### F-2 [P2] No input validation on `max_payload_bytes` and `max_json_depth` constructor parameters

`max_payload_bytes=0` flags everything; `max_payload_bytes=-1` flags including empty string. No constructor validation prescribed.

### F-3 [P2] Iterative depth check behavior on malformed bracket sequences is unspecified

Naive character scanning doesn't distinguish brackets in JSON strings from structural brackets. Unbalanced brackets have undefined behavior.

### F-4 [P2] Processing order does not specify whether structural failures short-circuit

"Fail fast" wording is ambiguous — does oversized-payload skip normalization entirely, or does it just run first?

### F-5 [P3] Empty string through MinimalScanner not explicitly tested

Test plan has "Clean input" but doesn't distinguish empty from benign.

### F-6 [P3] `to_dict()`/`from_dict()` does not specify Severity enum serialization

Should it serialize as `.name` ("HIGH") or `.value` ("high")?

### F-7 [P3] Exception guard catches `Exception` — `KeyboardInterrupt`/`SystemExit` propagation not called out

Correct behavior but not documented as intentional.

### F-8 [P3] `suppress_rules` with invalid rule IDs not addressed

Typo in rule ID silently fails to suppress. No warning/validation prescribed.

---

## Closure Table

| Finding | Status | Evidence |
|---------|--------|----------|
| F-1 | OPEN | — |
| F-2 | OPEN | — |
| F-3 | OPEN | — |
| F-4 | OPEN | — |
| F-5 | OPEN | — |
| F-6 | OPEN | — |
| F-7 | OPEN | — |
| F-8 | OPEN | — |

STATUS: GREEN
