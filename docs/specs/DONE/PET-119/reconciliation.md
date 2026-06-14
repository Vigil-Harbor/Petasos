# Reconciliation Report: PET-119

> Date: 2026-06-14
> Spec: docs/specs/TODO/PET-119.spec.md
> Merge: 3f79bdb (PR #97)
> Plane state: Done (group: completed)

## Summary

Full match. The shipped diff implements the spec exactly: `profile.pii_entities_extra` is now
an additive, per-scan, Presidio-only opt-in (Approach A), unioned over the scanner's own
`self._entities` base, with the shared instance never mutated. All six spec-named files changed
(profiles/__init__.py correctly left untouched per Decision 5), and the full backend-free pin
set + the load-bearing real-backend contract test + the CI lane row all shipped.

## Scope

| Spec file | In diff? | Notes |
|---|---|---|
| `petasos/scanners/presidio.py` | Yes | `extra_entities` kw on `scan()`, `_effective_entities()`, `_scan_sync(text, entities)` — as specified |
| `petasos/pipeline.py` | Yes | Stage-4 `isinstance(s, PresidioScanner)` extras; `_scan_one`/`_scan_with_breaker` conditional kwargs — as specified |
| `petasos/session/profiles/__init__.py` | No | Correctly **not** changed (Decision 5 — field/validation already exist from PET-117) |
| `tests/test_presidio_entity_scoping.py` | Yes | +184 — 8 backend-free pins + `TestProfilePresidioScoping` |
| `tests/conftest.py` | Yes | +7 — `NonSkippingLane("presidio", …, "TestProfilePresidioScoping", "extras-presidio")` |
| `.github/workflows/extras-presidio.yml` | Yes | +2 — `pipeline.py` + `profiles/__init__.py` added to `paths:` |

Unexpected files in diff (not in spec):
- `docs/specs/TODO/PET-119.test-output.txt` (+136) — standard ship-spec test-capture artifact; expected, not drift.

## Decisions

| # | Decision | Status | Evidence |
|---|---|---|---|
| 1 | Wire it (Option 1), additive opt-in only | Confirmed | `pipeline.py` Stage-4 passes `active_profile.pii_entities_extra` additively; no scope-out field added |
| 2 | Approach A — per-scan effective set as a call argument | Confirmed | `presidio.py` `_effective_entities(extra_entities)` computed per `scan()`, passed to `_scan_sync` |
| 3 | Union base is the scanner's own `self._entities` | Confirmed | `_effective_entities` → `resolve_presidio_entities(tuple(self._entities), tuple(extra_entities))` |
| 4 | Public `extra_entities`; `_scan_sync` takes the full per-call list | Confirmed | `scan(..., extra_entities=…)`; `_scan_sync(text, entities=None)` (`None` → `self._entities`) |
| 5 | Built-in profile lists kept as PET-117 curated; PERSON-under-cs/admin intended | Confirmed | no profile JSON in the diff; `profiles/__init__.py` untouched |
| 6 | Concurrency — `self._entities` never mutated, per-call list | Confirmed | `_effective_entities` returns a fresh local; `test_scan_does_not_mutate_self_entities` pins it |

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Field drives per-profile Presidio selection, additive via (A) | Met | `pipeline.py` extras wiring + `presidio.py` `_effective_entities` |
| 2 | A test fails if a profile-set PII entity silently no-ops again | Met | `TestProfilePresidioScoping::test_person_fires_under_customer_service_not_general` + negative/dedup pins |
| 3 | Presidio-lane real-backend tests non-skipping; `ci.yml` ML-free | Met | conftest `NONSKIPPING_LANES` presidio row; `extras-presidio.yml` paths widened |
| 4 | pytest / ruff / ruff format / mypy --strict green | Unverifiable (here) | captured in `PET-119.test-output.txt` |
| 5 | Default / no-profile detection unchanged | Met | `test_pipeline_no_profile_uses_base`, `test_pipeline_general_profile_empty_extras_uses_base` |
| 6 | Decision record present (A/B/C, opt-in-only, self._entities base, built-in audit) | Met | spec Decisions 1–6; wiki decision created by this close |
| 7 | After merge: /wiki-after-merge (or /spec-close) | Met | this close |

## Test Plan

| Test | Exists? | Location |
|---|---|---|
| no-extra uses base (negative pin) | Yes | `tests/test_presidio_entity_scoping.py::test_scan_no_extra_uses_base` |
| extra_entities additive | Yes | `…::test_scan_extra_entities_additive` |
| extra_entities dedup | Yes | `…::test_scan_extra_entities_dedup` |
| no-mutation (Decision 6) | Yes | `…::test_scan_does_not_mutate_self_entities` |
| unknown extra threads through (Presidio-is-the-filter) | Yes | `…::test_scan_unknown_extra_threads_through` |
| pipeline passes profile extras to Presidio | Yes | `…::test_pipeline_passes_profile_extras_to_presidio` |
| pipeline no-profile / general-empty use base | Yes | `…::test_pipeline_no_profile_uses_base`, `…::test_pipeline_general_profile_empty_extras_uses_base` |
| real-backend: PERSON under customer_service not general | Yes | `…::TestProfilePresidioScoping::test_person_fires_under_customer_service_not_general` |
| real-backend companion: admin PERSON fires | Yes | `…::TestProfilePresidioScoping::test_admin_person_fires` |

## Wiki-ready

Decisions and comprehension worth extracting to the wiki:
- Decision (Wire vs Deprecate): the dead-config field was made **live** (Option 1) rather than removed — chosen because the "expose every configuration surface" architecture goal favors making an advertised surface real; with the additive-only scope and the `self._entities`-as-base + per-call concurrency invariant. Wiki-worthy: constraining + reusable (the two-opt-in-surfaces layering with PET-109, and the concurrency rule for the shared spaCy instance).
- Comprehension: per-profile additive Presidio scoping — a new scan-time channel (`extra_entities`) from the pipeline to the Presidio scanner only, recomputed per `inspect()`, no shared-instance mutation; resolves the PET-117-observed inert field; widens Stage-9 anonymization under PII-watching profiles.

RECONCILED: yes DRIFT: 0
