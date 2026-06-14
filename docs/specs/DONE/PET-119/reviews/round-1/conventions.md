# Conventions Review — round 1

## Closure of round 0 findings
N/A — round 1.

## Findings

### F-1: Per-scan `isinstance(s, PresidioScanner)` described as "mirroring" the minimal-scanner special-case, but the existing idiom partitions once at construction
**Severity:** P3
**Where:** spec § Design → pipeline change #2; brief Approach (A).
Existing minimal special-case (`pipeline.py:287-294`) is a one-time partition at construction (`name`-check then `isinstance`), splitting `_minimal_scanner` from `_ml_scanners`. The spec runs `isinstance(s, PresidioScanner)` per-scan in the Stage-4 comprehension. Related but not the same pattern; "mirrors" slightly overstates the precedent. The per-scan approach is defensible (extras are profile-dependent, recomputed per call; only Presidio accepts the kwarg).
**Suggested fix:** Reword to "a bounded concrete-type special-case in the fan-out (the pipeline already special-cases scanner concrete types — `isinstance` at construction)"; optionally state why the check is per-call.

### F-2: New `scan_kwargs` dict-spread idiom in `_scan_one` — keep the mypy/protocol rationale in a code comment
**Severity:** P3
**Where:** spec § Design → pipeline change #4.
`_scan_one` currently calls `scanner.scan(...)` directly (`pipeline.py:219-222`). The conditional `scan_kwargs: dict[str, Any]` spread is a new local pattern in a hot path, justified (Presidio-only kwarg; generic Scanner protocol lacks it; unconditional keyword would fail mypy --strict and break non-Presidio scanners). `Any` already imported (`:12`).
**Suggested fix:** Add a one-line code comment noting extra_entities is Presidio-only and passed conditionally to keep the generic call protocol-conformant.

### F-3: Two opt-in surfaces for the noisy entities (config `presidio_entities_extra` + profile `pii_entities_extra`) — confirm intended layering vs PET-109 D2
**Severity:** P3
**Where:** spec § Decision 1/3.
PET-109 D2 made the noisy entities opt-in via the **config** field. This spec adds the **profile** field as a second additive channel unioned on top. Consistent with PET-109's additive/noise-posture intent (Decisions 2/3 preserve it); the two compose via the same `resolve_presidio_entities` dedup so a config+profile overlap can't double-fire. Flagged only so the human drift-check sees a second opt-in surface introduced deliberately.
**Suggested fix:** Optional one-line note making the two-surface layering explicit (config = global opt-in base; profile = per-profile opt-ins on top; same additive/dedup semantics; PET-109 D2 noise posture preserved on the default path).

## Convention checks that passed (no findings)
- Zero-dep base-install invariant: `from petasos.scanners.presidio import PresidioScanner` at pipeline top pulls no backend (all presidio imports in presidio.py are function-deferred; module-top is stdlib + petasos._types). Precedent: profiles/__init__.py:14 already imports KNOWN_PII_ENTITIES from presidio.py at module top.
- Pipeline never throws / fail-mode: threading stays inside the existing `_scan_one`/`_scan_with_breaker` try/except envelope.
- Concurrency invariant (Decision 6): `self._entities` never mutated; `_effective_entities` returns a fresh local. No-mutation pin specified.
- Frozen exports / no frozen-built-in edit: no JSON profile edit ships; customer_service.json:15 and admin.json:12 already carry PET-117-curated EMAIL_ADDRESS.
- PET-117 respected: pii_entities_extra parse/merge validation + KNOWN_PII_ENTITIES left as-is; spec consumes the field without redefining the guard.
- PET-106 pairing: proposed NONSKIPPING_LANES row tolerated by every meta-test (subset, derivation, orphan-flag); console correctly stays in _NON_SCANNER_EXTRAS; table already has two presidio rows, a third is consistent.
- @requires_presidio marker idiom + test placement match the established file convention.
- No stale-expectation breakage (profile tests assert pii_entities_extra membership at parse layer only).
- Decision-traceability norm honored (Approach A/B/C with rejected-alternative rationale).
- No backwards-compat shims (`_scan_sync(text, entities=None)` default is genuine live-caller compat, not dead code).
- Line-reference accuracy spot-checked against HEAD.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 0

STATUS: GREEN
