# Conventions Review -- round 2

## Closure of round 1 findings

All round 1 findings CLOSED:
- F-1 (P3): D1 remaps exempt_param_scan — category (c), rationale documented
- F-2 (P2): keyword-only separator is established pattern (AuditEmitter, AlertManager, LicenseValidator)
- F-3/F-8/F-9 (P4): _BUILTIN_NAMES consumer claim — spec now lists all consumers (L44)
- F-6 (P3): exempt_param_scan=False Done-when — category (c)
- F-7 (P2): Test #4 mock — matches existing patterns
- F-10 (P4): Test boilerplate inlining — correct for monkeypatch

## Findings

### F-1: Missing test_premium_integration.py update
**Severity:** P1
`tests/test_premium_integration.py:393` asserts `result.reason == "tool exempt per profile"` in `test_guard_with_profile_exempt`. After this spec's change, the default exempt path returns `reason="exempt-with-scan"`, breaking this assertion. The file is not listed in "Files changed" or "Existing test update".
**Suggested fix:** Add `tests/test_premium_integration.py` to "Files changed" table; add an existing test update entry for `test_guard_with_profile_exempt` (L373-393).

### F-2: Drawbridge audit decision divergence unacknowledged
**Severity:** P3
Wiki decision `2026-04-27-drawbridge-out-of-band-audit-emission.md` established audit integration for guard findings. Petasos diverges (consumer-side logging) but doesn't acknowledge the prior art.

### F-3–F-5: Silent Done-when additions (category c)
**Severity:** P3
`exempt_param_scan=False`, `_BUILTIN_NAMES` type, and custom profile overwrite — all well-motivated additions.

## Summary
P0: 0 | P1: 1 | P2: 0 | P3: 4 | P4: 0

STATUS: RED P0=0 P1=1 P2=0 P3=4 P4=0
