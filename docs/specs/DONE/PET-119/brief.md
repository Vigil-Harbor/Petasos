# PET-119 — Wire `profile.pii_entities_extra` into per-profile Presidio scoping (make the dead config live)

> **Status:** Draft brief · **Type:** bug / design decision · **Priority:** high
> **Decision taken:** **Option (1) — wire it.** *Not* deprecating the field.
> **Surfaced by:** PET-117 verification (the "Other implications" drift item)
> **Related:** PET-109 (config-level Presidio scoping, shipped), PET-112 (egress-scoped PII gate), PET-113 (profile descriptions / `agent_owner` deferral), PET-117 (dead `EMAIL` entity + parse-time typo guard)
> **Verified against:** `master` @ HEAD (`4444ff6`). The working tree is mid-edit — see *Verification note* at the end.

## Problem

A profile's `pii_entities_extra` field is exposed as a configuration surface —
parsed, merged, serialized in `to_dict`, and intended for frontend binding per
the architecture goal "expose every configuration surface" — but it **has no
scan-time consumer**. Operators and the dashboard can set it and observe no
effect on detection. It is dead config that *advertises* a capability the engine
does not deliver.

PET-117 deliberately stopped at removing the dead `EMAIL` string and guarding the
typo class, and filed this as the deeper latent bug: fixing a typo inside an inert
field is a no-op until the field is live. This ticket makes it live.

## Verified findings (against `master` @ HEAD `4444ff6`)

All claims re-checked at HEAD; line numbers match the committed file (the working
tree is dirty — see note).

- `git grep pii_entities_extra -- 'petasos/*.py'` returns **only** the profile
  dataclass: storage (`petasos/session/profiles/__init__.py:45`), `to_dict`
  (`:70`), parse (`:143`), merge (`:194`–`:198`, `:240`). It is **never passed to
  any scanner.**
- `_profile_hook` (`petasos/pipeline.py:849`) returns `self._minimal_scanner`
  only (`-> MinimalScanner`); its docstring confirms profile suppression now lives
  in Stage 4b and the hook does nothing else. **Nothing reconfigures the Presidio
  scanner per profile.**
- The Presidio scanner fixes its entity set **at construction**:
  `self._entities = list(DEFAULT_PRESIDIO_ENTITIES) if entities is None else list(entities)`
  (`petasos/scanners/presidio.py:151`). `scan()` (`:261`) takes only
  `text, direction, session_id` — no entity parameter — and `_scan_sync` (`:306`)
  passes `entities=self._entities` to `analyzer.analyze()` (`:309`).
- Construction happens at the console/plugin layer via `resolve_presidio_entities`
  (`petasos/console/hermes/plugin_api.py:107-111`), fed by `config.presidio_entities`
  / `presidio_entities_extra`, defaulting to `DEFAULT_PRESIDIO_ENTITIES`
  (`presidio.py:60`). **The pipeline receives an already-constructed scanner — it
  does not build Presidio itself.** (This shapes the wiring options below.)
- `PERSON` is a `NOISY_OPT_IN_ENTITIES` entity (`presidio.py:72`), not in the
  default band.

**Observable effect (benign-but-misleading), grep-confirmed:** `customer_service`
lists `["PERSON", "EMAIL", "PHONE_NUMBER"]` (`customer_service.json:15`) and `admin`
lists `["PERSON", "EMAIL", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE"]`
(`admin.json:12`). Under default config: `PERSON` silently does nothing (opt-in,
not in the default band); `PHONE_NUMBER` / `CREDIT_CARD` / `IBAN_CODE` fire only
because they are already in `DEFAULT_PRESIDIO_ENTITIES`, not because the profile
lists them; `EMAIL` is dead (PET-117). So a profile's PII list is decorative
today.

## Decision

**Wire it (Option 1).** Make `profile.pii_entities_extra` **additive on top of the
config-resolved entity set at scan time**: a profile can opt entities *in* (e.g.
`PERSON` for `customer_service`) that the config default does not enable. Deprecation
(Option 2) is explicitly **not** taken — the field stays and gains teeth.

### Effective entity contract (the semantics to implement)

For a given scan under `active_profile`:

```
effective_entities = resolve_presidio_entities(
    config.presidio_entities, config.presidio_entities_extra
) ∪ active_profile.pii_entities_extra        # order-preserving dedup
```

When no profile is active, `effective_entities` == the config-resolved set
(today's behavior — unchanged, so the default profile keeps PET-109's tightened
security band and its noise posture). Opt-in only; **scope-*out* is out of scope**
(see below).

## Implementation approaches (decision to record during build)

`analyzer.analyze()` already accepts an `entities` list **per call** — only the
`self._entities` *default* is fixed at `__init__`. spaCy/recognizers load once;
passing a different list per call is cheap. That makes a per-scan entity set the
natural lever and rules out rebuilding scanners. Three options were weighed:

- **(A) — RECOMMENDED — per-scan effective entity set, passed as a call argument.**
  The pipeline computes `effective_entities` from the active profile + config and
  hands it to the Presidio scan path for that call (e.g. an internal
  `scan(..., entities=...)` / `_scan_sync(text, entities)` parameter that defaults
  to `self._entities`). **Pros:** correct; no extra recognizers run on the default
  profile (preserves PET-109's noise posture); no per-profile instances; no shared
  mutable state. **Cons:** the `Scanner.scan()` protocol signature
  (`text, direction, session_id`) cannot carry an entity set, so this needs a
  Presidio-specific channel from the pipeline (a bounded special-case — the pipeline
  already special-cases the minimal scanner). **Hard invariant:** Presidio runs in
  `asyncio.to_thread` and the instance is shared across concurrent scans — the
  per-scan entity list **must** be passed as a call argument, **never** by mutating
  `self._entities` (concurrent scans on different profiles would race).

- **(B) — run a superset, filter findings per-profile (Stage-4b style).** Build
  Presidio with `default ∪ all-opt-ins`, then drop `petasos.presidio.*` findings
  whose entity isn't in the active profile's effective set, reusing the existing
  post-merge filter pattern. **Pros:** scanner untouched; mirrors Stage 4b
  suppression. **Cons:** the noisy recognizers (PERSON/LOCATION/…) then run on
  *every* scan and get filtered after the fact — reintroducing internally exactly
  the spaCy-NER cost and noise PET-109 deliberately removed, just hidden behind a
  filter. Wasteful and in tension with PET-109's intent. **Rejected unless (A)'s
  plumbing proves disproportionate.**

- **(C) — per-profile Presidio instances.** One scanner per profile entity set.
  **Rejected:** spaCy model memory/construction ×N, and construction lives at the
  console layer (`plugin_api.py`), not the pipeline — awkward and heavy.

Pick (A) unless implementation surfaces a blocker; record the choice and the
rejected alternatives (project norm: *decisions must be traceable*).

## Tests required

Per project rule, this update must add tests that prevent the bug class from
recurring.

- **Contract regression (the load-bearing one).** A profile that lists an
  opt-in entity *not* in the config default (`PERSON`) **produces a
  `petasos.presidio.person` finding under that profile and not under a profile
  without it** (e.g. `general`). This is the exact test PET-117 declined to add
  because it would false-green while the field was inert. It must **fail** if the
  field ever silently no-ops again.
- **Negative pin.** Under the default/no profile, the effective entity set equals
  the config-resolved set (no profile leakage; PET-109's default band intact).
- **Additivity / dedup.** A profile extra already in the default set does not
  duplicate findings or alter the default-profile result.
- **CI lane (PET-106).** The real-backend assertions live in the Presidio extra
  lane (`.github/workflows/extras-presidio.yml`) and run non-skipping under the
  `PETASOS_REQUIRE_PRESIDIO=1` collection guard — not as a mock. The default
  `ci.yml` lane stays ML-free.

## Decisions carried forward

- **Field stays — wired, not deprecated.** Resolves the "expose every config
  surface" promise honestly: the surface now does what it advertises.
- **Additive / opt-in only.** `pii_entities_extra` adds entities on top of the
  config-resolved set per profile. Per-profile *scope-out* (removing a default
  entity for a profile) is **not** in this ticket — it needs a separate opt-out
  field and conflicts with the `_extra` naming. (Out of scope.)
- **Default-profile behavior is unchanged.** No active profile ⇒ config-resolved
  set ⇒ PET-109's tightened band and noise posture preserved. Wiring must not
  regress the default path.
- **Concurrency invariant.** The per-scan entity set is a call argument; the shared
  Presidio instance's `self._entities` is never mutated per scan.
- **Audit the built-in profile lists now that they have teeth.** Once live,
  `customer_service`/`admin` `PERSON` will actually fire — reintroducing
  PERSON-on-technical-text findings *scoped to those profiles*. Confirm that is the
  intended posture for each built-in (this is the desired behavior for a
  customer-service profile, but `admin`'s list should be reviewed deliberately, not
  inherited). Record the call.
- **PET-117 becomes load-bearing, not cosmetic.** Once the field is live, a dead
  entity string (`EMAIL` vs `EMAIL_ADDRESS`) would cause a *real* missed detection,
  not just decorative drift. PET-117's `EMAIL → EMAIL_ADDRESS` fix and its
  parse-time typo guard are **prerequisites or must land together** — this ticket
  must not ship ahead of PET-117 without confirming the guard is in place. Note
  that once wired, `EMAIL_ADDRESS` in a profile extra is redundant with the default
  band (no harm; dedup handles it); the entities that actually change behavior are
  the opt-ins (`PERSON`, etc.).

## Done when

- `profile.pii_entities_extra` drives per-profile Presidio entity selection
  (additive over config), via the recorded approach; the dead-config gap is closed.
- A test pins the contract and **fails if a profile-set PII entity silently
  no-ops again** (the `PERSON`-under-`customer_service` integration test), plus the
  negative + additivity pins.
- The Presidio-lane real-backend test runs non-skipping under
  `PETASOS_REQUIRE_PRESIDIO=1` (PET-106 pairing intact); `ci.yml` stays ML-free.
- `pytest` / `ruff` / `mypy --strict` green.
- Default-profile detection is unchanged (regression pin green).
- Decision (approach A vs B vs C, and the opt-in-only scope) recorded; consistency
  with PET-117's frozen-profile entity edit and typo guard confirmed.
- After merge: `/wiki-after-merge <sha>` (and `/wiki-state-update petasos` if a
  state flip applies).

## Out of scope

- **Per-profile scope-*out* (opt-out of a default entity).** Needs a new field;
  this ticket is additive opt-in only.
- **Egress / direction-scoped PII (outbound-sink-only).** That is the
  PET-112 / PET-113 (`agent_owner`) scoping discussion — a *guard-layer* concern
  (`egress_sink_tools` / `_pre_tool_call`), distinct from making this flat entity
  field live at the *detector* layer.
- **The dead `EMAIL → EMAIL_ADDRESS` string fix and its parse-time typo guard** —
  owned by PET-117 (prerequisite; see *Decisions carried forward*).
- **Broader Presidio entity / threshold tuning** — owned by PET-109.
- **Profile description copy** — owned by PET-113.

## Other implications (drift check — candidate work items)

- **[Recommend filing — low] Frontend-binding metadata for a now-live field.** The
  dashboard exposes `pii_entities_extra` for editing; once it has runtime effect,
  the UI should surface *which* entity names are valid (reuse the PET-117
  known-recognizer-name set) and ideally flag entities already covered by config so
  operators understand additivity. Cosmetic, but it closes the loop on "expose
  every configuration surface" being *honest*. File against the console/dashboard
  area if not already covered by PET-113.
- **[Record] Profile-driven detection tests are now meaningful.** PET-117's brief
  noted "profile detects X" integration tests were false-green while detection was
  config-driven. After this ticket they become valid — the test-design caveat in
  PET-117 can be lifted for Presidio entities specifically.

---

### Verification note (working-tree state)

All findings above were verified against `master` @ HEAD (`4444ff6`); cited line
numbers are from the **committed** file. The current **working tree** is mid-edit:
`petasos/pipeline.py` is truncated (ends at an incomplete `if len(errors) >
pre_hook_error_count:` around line 769; HEAD is 909 lines with `_profile_hook` at
`:849`), and the built-in profile JSONs differ from HEAD (PET-117 work appears in
progress — bare `EMAIL` is gone from the working copy). The implementer must
resolve the local WIP and confirm PET-117's state before running the test gate;
the dead-config analysis itself is unaffected (it holds at HEAD and in the working
tree alike).
