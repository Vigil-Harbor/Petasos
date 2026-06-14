# Correctness Review — round 1

## Closure of round 0 findings
N/A — round 1.

## Findings

### F-1: Stage-4 fan-out line anchor is slightly off (`:617-628` vs. the actual call site `:618-623`)
**Severity:** P3
**Where:** spec § Design → `petasos/pipeline.py`, item 2 ("Stage 4 fan-out (`:617-628`)")
At HEAD `bdfe8dc`, the `elif self._ml_scanners:` block runs `pipeline.py:617-628`, but the `tasks = [...]` comprehension the spec actually rewrites is `:618-623`, and the `self._scan_with_breaker(...)` call to be widened is `:619-621`. The cited range over-scopes the edit region (includes the gather/_normalize_gather_result block the spec doesn't touch). Intent unambiguous from prose + code block.
**Suggested fix:** Narrow the anchor to `:618-623` (the `tasks` comprehension) or `:619-621` (the breaker call).

### F-2: `plugin_api.py` construction-call anchor cited as `:107-114`/`:107-111`; the actual ctor call is `:109-114`
**Severity:** P3
**Where:** spec § Scope → "Files to leave alone" (`:107-114`) and § Decision 3
`plugin_api.py:107` is the `from petasos.scanners.presidio import resolve_presidio_entities` line; the ctor call is `:109-114`. Load-bearing claim (scanner's `self._entities` IS the config-resolved base → Decision 3 equals the brief's formula) is correct; only the anchor is imprecise.
**Suggested fix:** Cite `:109-114` for the construction call.

### F-3: Custom-profile `pii_entities_extra` ordering is already non-deterministic upstream — "order-preserving dedup" only literally holds for built-ins
**Severity:** P3
**Where:** spec § Decision 4 / § Design (`_effective_entities`) and Test plan (`test_pipeline_passes_profile_extras_to_presidio` asserts "order-preserving, deduped")
`_effective_entities` preserves order over its input, but for *custom merged* profiles input order is already lost: `_merge_with_base` (`profiles/__init__.py:241`) computes `pii = tuple(set(pii) | set(val))` — set-union, non-deterministic. Built-ins flow through `_parse_profile:175` `tuple(data.get(...))` (JSON order preserved), so the spec's built-in tests are unaffected and the entity *set* passed to Presidio is correct regardless of order (`analyze` is order-insensitive). Worth a one-line acknowledgment so a future reader doesn't write an order-asserting test against a custom-merged profile.
**Suggested fix:** Note that for custom-merged profiles extras' relative order is set-defined upstream; "order-preserving" applies to the union operation; keep the order-asserting test scoped to the built-in path (as it already is).

## Cross-section consistency walk (clean — no findings)
- PresidioScanner.scan widening keeps it a valid Scanner protocol member and passes `_validate_scanner` (`_types.py:164-169` requires only direction/session_id present; optional kwarg removes neither).
- `**scan_kwargs` (`dict[str, Any]`) splat type-checks under mypy --strict and does not leak `extra_entities` to non-Presidio scanners (only added when `is not None`, set only for `isinstance(s, PresidioScanner)`).
- Anchors verified exact at HEAD: presidio.py `self._entities` :164, `_scan_sync` :319, `resolve_presidio_entities` :88, Sequence under TYPE_CHECKING :14-15, `from __future__` :1; pipeline.py `_scan_one` :208, `_scan_with_breaker` :782, `Any` import :12, Sequence TYPE_CHECKING :46, `active_profile` param :572; ResolvedProfile.pii_entities_extra :46, strict parse :176, lenient merge :240.
- Profile JSONs match Decision 5 verbatim (post-PET-117 EMAIL_ADDRESS).
- New third presidio NONSKIPPING_LANES row passes every meta-test (subset `<=`, derivation, orphan-flag both directions; collection guard satisfied because the class lives in test_presidio_entity_scoping.py which the lane runs).
- No external direct callers of `presidio._scan_sync`.
- `_resolve_profile(None)` → None → base-only: negative pin satisfiable.
- No existing test asserts PERSON-absence under customer_service/admin (only test_profiles.py:421-422 parse-level).

## Done-when coverage
All Plane PET-119 Done-when criteria map to spec sections. The ticket's "ideally scope out" is non-mandatory and explicitly deferred with rationale.

## Summary
P0: 0 | P1: 0 | P2: 0 | P3: 3 | P4: 0
All three findings are P3 anchor-precision / framing nits; none blocks the gate.

STATUS: GREEN
