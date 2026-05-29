# PET-10 Correctness Review — Round 1

**Spec:** `docs/specs/TODO/PET-10.spec.md`
**Brief:** `docs/briefs/PET-10-jwt-license-premium-wiring.md`
**Round:** 1

---

## Findings

### F-1 — `tests/test_guard.py` missing from files-to-change (P0)

**Severity:** P0
**Section:** Scope → Files to change

`tests/test_guard.py` contains 10 calls to `pipe.activate()` with no arguments (the PET-7 signature). PET-10 changes `activate()` to require a `key: str` argument. Every one of these calls will fail with `TypeError: activate() missing 1 required positional argument: 'key'`.

The file is not listed in the scope table under "Files to change" and the test plan (item 33) only mentions `test_premium_integration.py`, not `test_guard.py`.

**Evidence:** Grep of `tests/test_guard.py` for `activate()` calls — 10 occurrences, all no-arg.

**Fix:** Add `tests/test_guard.py` to the files-to-change table with change description "Update `activate()` calls to `activate(valid_key)`". Add explicit test plan item for guard test updates.

---

### F-2 — Internal contradiction on `profiles/__init__.py` scope (P1)

**Severity:** P1
**Section:** Scope → Files to change vs. Design § Hardening

The scope table lists `petasos/premium/profiles/__init__.py` with change "Defensive copy in `ProfileResolver.resolve()` for built-in profiles". However, the hardening section (Design §5) concludes: "**No change needed** — `ResolvedProfile` fields are all immutable types (`frozenset`, `MappingProxyType`, `tuple`, `float`, `str`, `None`)."

These two statements contradict each other. Either a defensive copy is needed (scope table is correct) or it isn't (hardening analysis is correct).

**Fix:** The hardening analysis is correct — `ResolvedProfile` is frozen with all-immutable fields. Remove `profiles/__init__.py` from the files-to-change table, or change its entry to "Verify only — no code changes".

---

### F-3 — `petasos/premium/_keys/__init__.py` missing from files-to-change (P1)

**Severity:** P1
**Section:** Scope → Files to change

Design §2 says: "`petasos/premium/_keys/__init__.py` — empty, makes it a package for `importlib.resources`." This is a new file that must be created, but it doesn't appear in the scope table. Without it, `importlib.resources.files("petasos.premium._keys")` will fail because `_keys` won't be recognized as a package.

**Fix:** Add `petasos/premium/_keys/__init__.py` to the files-to-change table with "**New.** Empty `__init__.py` for `importlib.resources` package discovery."

---

## Closure Table

| Finding | Status |
|---------|--------|
| F-1 | OPEN |
| F-2 | OPEN |
| F-3 | OPEN |

STATUS: RED P0=1 P1=2
