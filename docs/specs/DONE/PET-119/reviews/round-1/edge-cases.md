# Edge-Cases Review — round 1

## Closure of round 0 findings
N/A — round 1.

## Findings

### F-1: `general`-profile empty-extras path threads `extra_entities=[]` (not `None`), diverging from the no-profile path the negative pin covers
**Severity:** P2
**Pre-ship recommended:** yes
**Where:** spec § Design pipeline steps 2 & 4; test plan `test_pipeline_no_profile_uses_base`.
An active profile with `pii_entities_extra == ()` — the `general` built-in (`general.json:8`), and the *default* profile (`pipeline.py:486`). With `general` active: `active_profile is not None and isinstance(s, PresidioScanner)` is true → fan-out passes `extra_entities=()` → `_scan_one` sees `() is not None` true → `scan(..., extra_entities=[])` → `_effective_entities([])` relies on falsy `[]` to return base. Correct, but a structurally different branch from the no-profile path (keyword omitted). The most common live path (`profile="general"`) has no pipeline-level pin.
**Suggested fix:** Add backend-free `test_pipeline_general_profile_empty_extras_uses_base` — `inspect(text, profile="general")` records exactly `list(DEFAULT_PRESIDIO_ENTITIES)`.

### F-2: Unknown custom-profile entity reaches `analyzer.analyze(entities=[...])` — "silently ignored" is asserted but unpinned and version-dependent
**Severity:** P2
**Where:** spec § Design notes ("Unknown custom-profile extras … silently ignored by Presidio").
A custom profile (dict path) with an unknown-but-retained name (lenient merge `strict=False`, `profiles/__init__.py:240-241` keeps it) flows through `_effective_entities` → `resolve_presidio_entities` (no `KNOWN_PII_ENTITIES` filter) → `analyze(entities=["BOGUS", ...])`. Current presidio-analyzer ignores unknown names (no raise), so the claim holds for the tested version, but it is an external-contract assumption with zero coverage. A future strict presidio would raise → caught by `_scan_one`'s `except BaseException` → degraded ScanResult → under `degraded` fail-mode, all content blocked under that custom profile, with no tripwire naming the entity.
**Suggested fix:** Add a backend-free pin (recording analyzer) that a custom profile with an unknown extra records `base + ["NOT_A_REAL_ENTITY"]` to `analyze` (pins threading), and document that filtering unknowns is deliberately NOT done (Presidio is the filter). Optionally note `_effective_entities` could intersect with `KNOWN_PII_ENTITIES` for future robustness — a design call to record, not silently assume.

### F-3: Non-str / malformed `pii_entities_extra` entries can reach `_effective_entities` via the lenient custom-merge path
**Severity:** P2
**Where:** spec § Design `_effective_entities`; profiles merge `profiles/__init__.py:236-241`.
A custom profile with `pii_entities_extra=["PERSON", 123, None]` — lenient merge warns but retains hashable non-str (`set(pii)|set(val)`). `dict.fromkeys((*base, "PERSON", 123, None))` does not raise (hashable), producing `[...,123,None]` → `analyze(entities=[...,123,None])`. Presidio tolerance of non-str members is untested/version-dependent; a `.upper()` internally would raise → caught → degraded → content blocked, no tripwire. Spec's type annotations assume all extras are str; mypy --strict can't catch runtime-JSON `Any`.
**Suggested fix:** Either (a) state non-str retention is the merge path's pre-existing contract (out of scope) and acknowledge the degraded-block consequence, or (b) `_effective_entities` defensively skips non-str (`isinstance(e, str)`). A backend-free pin with a non-str extra documents whichever choice.

### F-4: The load-bearing real-backend test's threshold reliability is hand-waved ("tune phrasing") — PERSON NER flakiness is a known spaCy risk
**Severity:** P2
**Where:** spec § Test plan, real-backend contract.
PERSON is a spaCy-NER entity; confidence depends on context/capitalization/model version. A bare "John Smith" can score below 0.35, and tagging shifts across releases. This is the single most-likely-to-flake assertion and it is the load-bearing contract test (Done-when #2). The negative half (general → no PERSON) is robust; the positive half carries the risk.
**Suggested fix:** Commit to a concrete NER-friendly corpus (full name + strong contextual cue, e.g. "Customer name: Dr. Margaret Thompson called about her account.") and require verifying the score margin on the Hermes venv before the gate. Note a fallback (assert on another opt-in entity) but keep PERSON-under-customer_service as the named contract — phrasing must be pinned, not deferred.

### F-5: Stage-9 anonymize interaction — newly-detectable per-profile entities flow into anonymization
**Severity:** P3
**Where:** not mentioned; code `pipeline.py:710-739` (Stage 9), `:719-725` (`config.pii_entities` D7 filter).
Under customer_service/admin, PERSON findings now appear in `merged`. `_recover_entity_type("petasos.presidio.person")` → "PERSON" (`presidio.py:346-349`), so a non-PERSON `config.pii_entities` correctly filters them out (narrowing works). But with `anonymize=True` and `pii_entities=()` (anonymize-all default), PERSON spans are now redacted/hashed in sanitized output under those profiles where they never existed before — a real, intended-but-undocumented output change. Done-when #5 covers only the no-profile path.
**Suggested fix:** One sentence documenting the consequence (intended); optionally a backend-free assert that `_recover_entity_type` round-trips PERSON into the D7 allowed-set filter.

### F-6: Circuit-breaker / timeout accounting correctly unaffected but unpinned; `list(extra_entities)` copy is outside the timed await
**Severity:** P3
**Where:** spec § Design `_scan_with_breaker`/`_scan_one`.
Verified: breaker counts only `_TIMEOUT_ERROR_PREFIX` (`pipeline.py:835`); the kwargs build + `list()` copy is before `asyncio.wait_for`, negligible. Claim holds; no test guards the threaded path against a future refactor.
**Suggested fix:** Optional backend-free pin (Presidio sleeps past timeout under a profile with extras → still a timeout ScanResult, breaker increments), or note it's unpinned-by-design.

### F-7: No runtime debuggable tripwire when a profile-set entity silently fails to fire (vs merge-time)
**Severity:** P3
**Where:** brief § Tests required; spec Notes.
Merge-time warning covers unknown custom names, but no runtime signal distinguishes "profile asked for PERSON, not present in text" from "wiring dropped it." CI is the recurrence net, and the presidio lane triggers only on `paths:` changes — a pipeline refactor in an unlisted file could bypass the contract test on its PR.
**Suggested fix:** Optional DEBUG log in `_effective_entities` when extras non-empty; or document runtime observability is out of scope and CI is the contract net, noting the paths-triggered lane gap (mitigated by adding pipeline.py to paths).

## Summary
P0: 0 | P1: 0 | P2: 4 | P3: 3 | P4: 0
Clean verifications: concurrency invariant genuinely satisfied (fresh local list, no `self._entities` reassignment); `_validate_scanner` accepts extra keyword-only params; conftest 4th presidio row tolerated by all meta-tests; lane collects test_presidio_entity_scoping.py so the armed class won't fail the guard; early_exit path skips ML fan-out and assumes nothing about extra_entities; mypy --strict kwargs-splat sound.

STATUS: GREEN
