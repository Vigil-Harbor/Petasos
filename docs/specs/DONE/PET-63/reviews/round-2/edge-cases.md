# Edge-Cases Review -- round 2

## Closure of round 1 findings

All 8 round-1 edge-case findings closed or addressed. Cross-lens closure verified.

| ID | Title | Status | Evidence |
|---|---|---|---|
| F-1 | ValueError swallowed by pipeline | CLOSED | Files-left-alone section acknowledges pipeline catch as expected degradation |
| F-2 | Whitespace-only hash_key bypass | CLOSED | Out of Scope explicitly notes whitespace-only strings accepted |
| F-3 | assert stripped by -O | CLOSED | Layer 4 uses explicit raise ValueError |
| F-4 | Direct callers bypass anonymize() guard | CLOSED | Layer 4 adds own guard inside _anonymize_engine_path() |
| F-5 | No pipeline integration test | CLOSED | Config guard makes path unreachable; test 8 covers config level |
| F-6 | Line references | CLOSED | Verified accurate |
| F-7 | not hash_key type confusion | CLOSED | API is typed; non-string falsy values are caller error |
| F-8 | operator validate() timing | CLOSED | Informational only |

## Findings

### F-1: operate() accepts empty hmac_key (P2)
`_HmacSha256Operator.operate()` checks key presence but not emptiness. If called without validate(), empty key produces degenerate HMAC. Low risk since Presidio calls validate() before operate().

### F-2: Config guard skipped when anonymize=False (P2)
`PetasosConfig(anonymize=False, redaction_mode="hash", hash_key="")` passes validation. Frozen dataclass makes runtime mutation hard. Low risk.

### F-3: Tests 4-5 require presidio extra installed (P2)
`_make_hmac_operator_class()` imports from presidio. Tests need skip guard. Existing tests already use `@requires_presidio_libs`.

### F-4: Test 1 ambiguous about hash_key=None vs omitted (P3)
Both paths produce ValueError; spec should clarify which is tested.

### F-5: Layer 4 error message lacks repr(hash_key) (P3)
Including the actual value would help diagnose how the outer guard was bypassed.

### F-6: Module-level singleton caching of operator class (P3)
Operator-level guard only effective after clean module load. No runtime concern.

## Summary
P0: 0 | P1: 0 | P2: 3 | P3: 3

STATUS: GREEN
