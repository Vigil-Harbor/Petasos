# PET-119 — Wire `profile.pii_entities_extra` into per-profile Presidio scoping

> **Brief:** `docs/specs/TODO/PET-119.brief.md`
> **Plane:** PET-119 (project `5bff6316-84ea-4103-b9e2-4861ac9c226a`, namespace `petasos`)
> **Verified against:** `master` @ HEAD `bdfe8dc` (PET-117 merged — this spec's prerequisite is in the tree).
> **Type:** bug / dead-config wiring · **Priority:** high

## Goal

Make a profile's `pii_entities_extra` field actually drive Presidio detection. Today the
field is parsed, validated, merged, and serialized for frontend binding but has **no
scan-time consumer** — operators can set it and observe no effect. This ticket makes it
**additive on top of the config-resolved entity set at scan time**: a profile may opt
entities *in* (e.g. `PERSON` for `customer_service`) that the config default does not
enable. When no profile is active, detection is byte-for-byte today's behavior. The fix
is a small, bounded Presidio-specific channel from the pipeline to the Presidio scanner,
plus the tests that fail if the field ever silently no-ops again.

## Scope

**Files to change (3 source + test/CI):**

- `petasos/scanners/presidio.py` — add an additive, per-call `extra_entities` keyword to
  `PresidioScanner.scan()`; thread a per-call entity list into `_scan_sync`. `self._entities`
  is never mutated.
- `petasos/pipeline.py` — at the Stage-4 fan-out, pass the active profile's
  `pii_entities_extra` to the Presidio scanner only; thread an optional `extra_entities`
  through `_scan_with_breaker` and `_scan_one`.
- `petasos/session/profiles/__init__.py` — **no behavior change.** The `pii_entities_extra`
  field (`:46`), its strict parse-time validation (`:176`) and lenient merge validation
  (`:240`) already exist (PET-117). Audited and left as-is (see Decision 5).
- `tests/test_presidio_entity_scoping.py` — add backend-free pins (effective-set
  computation, dedup, no-mutation) and a new real-backend class `TestProfilePresidioScoping`
  (the load-bearing PERSON-under-`customer_service` contract).
- `tests/conftest.py` — add one `NonSkippingLane` row arming `TestProfilePresidioScoping`
  under `PETASOS_REQUIRE_PRESIDIO`.
- `.github/workflows/extras-presidio.yml` — add `petasos/pipeline.py` and
  `petasos/session/profiles/__init__.py` to the `paths:` trigger so the real-backend
  contract test runs when the wiring changes.

**Files to leave alone:**

- `petasos/console/hermes/plugin_api.py` — already builds `PresidioScanner` from
  `resolve_presidio_entities(config.presidio_entities, config.presidio_entities_extra)`
  (ctor call at `:109-114`). The scanner's `self._entities` is therefore the config-resolved
  base by construction; no change needed.
- `petasos/config.py` — no new fields; the `_extra` field lives on the profile, not config.
- The built-in profile JSONs (`customer_service.json`, `admin.json`, `general.json`, …) —
  PET-117 already curated their entity lists (`EMAIL`→`EMAIL_ADDRESS`). Left as-is per
  Decision 5.

## Decisions

### Decision 1 — Wire it (Option 1), additive opt-in only

Per the brief: the field stays and gains teeth. `pii_entities_extra` adds entities on top of
the config-resolved set, per profile. Per-profile *scope-out* (removing a default entity for
one profile) is **out of scope** — it needs a separate opt-out field and conflicts with the
`_extra` naming.

### Decision 2 — Approach (A): per-scan effective entity set, passed as a call argument

Of the brief's three approaches, take **(A)**. `analyzer.analyze()` already accepts an
`entities` list per call; spaCy/recognizers load once, so a per-call entity list is cheap.

- **(A) chosen** — compute the effective set per scan and hand it to the Presidio scan path
  as a call argument. No extra recognizers run on the default profile (preserves PET-109's
  noise posture); no per-profile scanner instances; no shared mutable state.
- **(B) superset + post-filter — rejected.** Running PERSON/LOCATION on *every* scan and
  filtering after the fact re-introduces exactly the spaCy-NER cost/noise PET-109 removed.
- **(C) per-profile instances — rejected.** spaCy model memory ×N; construction lives at the
  console layer, not the pipeline.

### Decision 3 — The union base is the scanner's own `self._entities`, not a pipeline-side re-derivation from config

The brief's contract is
`effective = resolve_presidio_entities(config.presidio_entities, config.presidio_entities_extra) ∪ profile.pii_entities_extra`.
Because `plugin_api.py:107-114` constructs the scanner with
`entities=resolve_presidio_entities(config.presidio_entities, config.presidio_entities_extra)`,
the scanner's `self._entities` **is** that config-resolved set. We therefore base the union
on `self._entities` (inside the scanner, where it lives) rather than re-deriving it from
`self._config` in the pipeline.

**Rationale:** (1) identical result to the brief's formula under the standard construction
path; (2) more robust — a test or embedder that constructs the scanner with an explicit
`entities=` and a different config never drifts, because the base is whatever the scanner
actually detects with; (3) the scanner stays the single source of truth for its base; (4)
the pipeline never reaches into the scanner's privates — it passes only the additive extras.

### Decision 4 — Public API is additive (`extra_entities`); the internal `_scan_sync` takes the full per-call list

`PresidioScanner.scan()` gains a keyword-only `extra_entities: Sequence[str] | None = None`
(additive — the scanner unions it with `self._entities`). `_scan_sync` gains
`entities: list[str] | None = None` (the *full* per-call list; `None` → `self._entities`,
preserving existing direct `_scan_sync(text)` callers/tests). This separates a clear public
additive API from the low-level replacement parameter, and reuses the order-preserving-dedup
`resolve_presidio_entities` for the union.

### Decision 5 — Built-in profile lists are kept as PET-117 curated them; PERSON-under-`customer_service`/`admin` is the intended posture

Once live, `customer_service` (`["PERSON","EMAIL_ADDRESS","PHONE_NUMBER"]`) and `admin`
(`["PERSON","EMAIL_ADDRESS","PHONE_NUMBER","CREDIT_CARD","IBAN_CODE"]`) will make `PERSON`
actually fire under those profiles. This is **intended and unchanged**:
`customer_service`'s own description says it "watches conversations for personal data such as
names and phone numbers"; `admin` is the strictest posture ("early lockdown beats
convenience"), so broader detection is consistent. The default path (`general` / no profile)
is untouched. No JSON edit ships in this ticket. (If `admin`'s `PERSON` is later judged too
noisy, that is a one-line JSON tuning change, tracked separately — not a blocker here.)

### Decision 6 — Concurrency invariant (hard constraint)

Presidio runs in `asyncio.to_thread` and the instance is shared across concurrent scans. The
per-scan effective list **must** be a call argument and `self._entities` **must never** be
mutated per scan — concurrent scans on different profiles would otherwise race. The design
computes a fresh local list per call and passes it down; `self._entities` is read-only after
construction. A test pins that `scan(..., extra_entities=…)` leaves `self._entities` unchanged.

## Design

### `petasos/scanners/presidio.py`

Widen the scan path with an additive per-call entity channel. `self._entities` (`:164`)
stays the constructed base and is never reassigned.

```python
async def scan(
    self,
    text: str,
    *,
    direction: Direction = "inbound",
    session_id: str | None = None,
    extra_entities: Sequence[str] | None = None,   # NEW — additive opt-ins (PET-119)
) -> ScanResult:
    ...
    self._ensure_loaded()
    effective = self._effective_entities(extra_entities)
    findings = await asyncio.to_thread(self._scan_sync, text, effective)
    ...
```

```python
def _effective_entities(self, extra_entities: Sequence[str] | None) -> list[str]:
    # Additive, order-preserving dedup over the scanner's own base set. `self._entities`
    # is always non-empty (>= DEFAULT_PRESIDIO_ENTITIES), so resolve_presidio_entities
    # never trips its empty-set guard. self._entities is NOT mutated.
    if not extra_entities:
        return self._entities
    return resolve_presidio_entities(tuple(self._entities), tuple(extra_entities))
```

`_scan_sync` (`:319`) takes the per-call list, defaulting to the base so existing direct
callers (`_scan_sync(text)`) are unchanged:

```python
def _scan_sync(self, text: str, entities: list[str] | None = None) -> list[ScanFinding]:
    results = self._analyzer.analyze(
        text=text,
        entities=self._entities if entities is None else entities,
        language=self._language,
        score_threshold=self._score_threshold,
    )
    ...
```

Notes:
- `Sequence` is already imported under `TYPE_CHECKING` (`presidio.py:14-15`); the runtime
  `tuple(...)` calls don't need it. `resolve_presidio_entities` (`:88`) already does
  order-preserving dedup via `dict.fromkeys` and returns a non-empty `list[str]`.
- Adding an *optional* keyword to `scan()` keeps `PresidioScanner` structurally compatible
  with the `Scanner` protocol (the protocol's `scan(text, *, direction, session_id)` callers
  still work). The implementation must keep passing `_validate_scanner` — there is an existing
  Pipeline-construction path that validates it.
- **Unknown / non-str custom-profile extras are deliberately NOT filtered here — Presidio is
  the filter.** Custom (dict-path) profiles may retain unknown names (lenient merge warn-path,
  `profiles/__init__.py:240-241`) or hashable non-str entries (`set(pii) | set(val)` keeps
  ints/None; an unhashable list/dict raises at merge time, pre-existing). `dict.fromkeys`
  tolerates hashable non-str (no raise), and current `presidio-analyzer` ignores `entities`
  members it has no recognizer for. If a future Presidio rejects unknown/non-str members, the
  error is caught by `_scan_one`'s `except BaseException` → an error `ScanResult` (under the
  default `degraded` fail-mode this blocks content under that custom profile). We do **not**
  intersect extras with `KNOWN_PII_ENTITIES` at scan time — the merge-time warning already
  flagged unknowns; hardening that path is a deliberate non-goal (see `## Deferred (P2+)`).
- **Order-preserving caveat.** `_effective_entities` preserves order over its input, but a
  *custom-merged* profile's extras order is already set-defined upstream (`_merge_with_base:241`,
  `tuple(set(pii) | set(val))`). Order-preservation therefore applies to the union operation,
  not to merged-custom input; `analyzer.analyze` is order-insensitive, and the order-asserting
  tests are scoped to **built-in** profiles (which flow through `_parse_profile:175`,
  JSON-order-preserving).

### `petasos/pipeline.py`

Thread an optional `extra_entities` from the Stage-4 fan-out down through the breaker to the
scan call, set **only** for the Presidio scanner. Detect Presidio with `isinstance(s,
PresidioScanner)` — a bounded concrete-type special-case in the fan-out. (The pipeline already
special-cases scanner concrete types — `isinstance(s, MinimalScanner)` partitions at
construction, `pipeline.py:287-294`. The Presidio check is per-call rather than a one-time
partition because the extras are profile-dependent and must be recomputed each `inspect()`,
and only `PresidioScanner.scan` accepts the keyword.)

1. **Module import (dep-free):** add `from petasos.scanners.presidio import PresidioScanner`
   at module top. `presidio.py`'s top level imports stdlib + `petasos._types` only — no
   backend import — so this preserves the zero-dep base-install invariant.

2. **Stage 4 fan-out (`:618-623` — the `tasks = [...]` comprehension)** — compute the
   per-scanner extras inline:

```python
tasks = [
    self._scan_with_breaker(
        s, normalized_text, direction=direction, session_id=session_id,
        extra_entities=(
            active_profile.pii_entities_extra
            if active_profile is not None and isinstance(s, PresidioScanner)
            else None
        ),
    )
    for s in self._ml_scanners
]
```

3. **`_scan_with_breaker` (`:782`)** — add `extra_entities: Sequence[str] | None = None`
   and forward it to `_scan_one(...)`. Breaker/timeout state is unchanged.

4. **`_scan_one` (`:208`)** — add `extra_entities: Sequence[str] | None = None`. Pass it to
   `scanner.scan()` only when set, via a kwargs dict so non-Presidio scanners never receive
   the keyword and mypy `--strict` doesn't flag the generic `Scanner` call:

```python
# extra_entities is Presidio-only; passed conditionally so the generic Scanner.scan() call
# stays protocol-conformant under mypy --strict (no keyword reaches non-Presidio scanners).
scan_kwargs: dict[str, Any] = {"direction": direction, "session_id": session_id}
if extra_entities is not None:
    scan_kwargs["extra_entities"] = list(extra_entities)
return await asyncio.wait_for(
    scanner.scan(normalized_text, **scan_kwargs),
    timeout=timeout,
)
```

`Any` is already imported (`pipeline.py:12`); `Sequence` is available under `TYPE_CHECKING`
(`:46`).

**Why this honors every invariant:**
- *No-profile / default path unchanged:* when `active_profile is None`, `extra_entities` is
  `None` → `_scan_one` omits the keyword → the scanner uses `self._entities` → today's exact
  behavior (negative pin).
- *Empty-extras profile (e.g. `general`, `pii_entities_extra == ()`):* falsy → `_effective_entities`
  returns the base unchanged. No extra recognizers run.
- *Other scanners untouched:* `extra_entities` is only computed for `isinstance(s, PresidioScanner)`.
- *Concurrency:* the effective list is a per-call local; `self._entities` is never mutated.
- *Never-throws / fail-mode:* the change is inside the existing `_scan_one`/`_scan_with_breaker`
  try/except envelope; an unexpected `scan()` error still returns an error `ScanResult`.

### Two opt-in surfaces (config base + profile additive)

PET-109 D2 made the five noisy entities opt-in via the **config** `presidio_entities_extra` (the
global base). This ticket adds the **profile** `pii_entities_extra` as a *second* additive
channel, unioned on top per profile via the same `resolve_presidio_entities` order-preserving
dedup — so a config-and-profile overlap (both list `URL`) cannot double-fire. Layering is
deliberate and consistent with PET-109: config = global opt-in base; profile = per-profile
opt-ins on top; the noise posture on the default/no-profile path is preserved.

### Interaction: Stage-9 anonymization

Making the field live also widens the per-profile finding set that reaches Stage 9
(`pipeline.py:710-739`). `_recover_entity_type("petasos.presidio.person") == "PERSON"`
(`presidio.py:346-349`), so PET-109 D7's `config.pii_entities` narrowing filter (`:719-725`)
continues to gate the new entities correctly (a non-`PERSON` `pii_entities` excludes them). One
intended consequence to note: with `anonymize=True` and the anonymize-all default
(`pii_entities=()`), `PERSON` spans are now redacted/hashed in `sanitized_content` under
`customer_service`/`admin`, where they previously never appeared — desired behavior for those
PII-watching profiles. The default/no-profile path is unaffected (Done-when #5).

### `.github/workflows/extras-presidio.yml`

Add the wiring files to the `paths:` trigger (`:10-16`) so a change to the pipeline wiring or
the profile field re-runs the real-backend contract test:

```yaml
    paths:
      - "petasos/scanners/presidio.py"
      - "petasos/pipeline.py"                       # NEW (PET-119 wiring)
      - "petasos/session/profiles/__init__.py"      # NEW (pii_entities_extra source)
      - "petasos/config.py"
      - "petasos/console/hermes/plugin_api.py"
      - "tests/test_presidio_scanner.py"
      - "tests/test_presidio_entity_scoping.py"
      - "tests/conftest.py"
```

### `tests/conftest.py`

Add one row to `NONSKIPPING_LANES` (`:144-176`) arming the new contract class:

```python
    NonSkippingLane(
        "presidio",
        "PETASOS_REQUIRE_PRESIDIO",
        "presidio_analyzer",
        "TestProfilePresidioScoping",   # PET-119 profile→Presidio wiring contract
        "extras-presidio",
    ),
```

This is tolerated by every meta-test in `tests/test_ci_extras_lanes.py`:
`test_presidio_is_armed` uses `<=` (subset), `test_nonskipping_table_matches_derivation`
derives `env_flag`/`lane` from `extra="presidio"` (both already correct), and
`test_no_orphan_require_flags` maps the flag↔lane (unchanged). The class is `@requires_presidio`,
so on the lane (presidio + spaCy installed) it is collected unskipped — satisfying the guard;
on `ci.yml` (flag unset) it self-skips with the guard disarmed.

## Test plan

New and updated tests (recurrence prevention is the explicit requirement: a test must **fail**
if the field silently no-ops again).

### Backend-free pins — run on every lane (`ci.yml` included), in `tests/test_presidio_entity_scoping.py`

A small fake analyzer records the `entities` list `analyzer.analyze` receives, with no spaCy
dependency:

```python
class _RecordingAnalyzer:
    def __init__(self) -> None:
        self.entities: list[str] | None = None
    def analyze(self, *, text, entities, language, score_threshold):
        self.entities = list(entities)
        return []

def _recording_scanner(**kw) -> tuple[PresidioScanner, _RecordingAnalyzer]:
    s = PresidioScanner(**kw)
    rec = _RecordingAnalyzer()
    s._analyzer = rec
    s._loaded = True
    return s, rec
```

- `test_scan_no_extra_uses_base` (**negative pin**) — `scan(text)` and `scan(text, extra_entities=())`
  / `extra_entities=None` each record exactly `list(DEFAULT_PRESIDIO_ENTITIES)`; no leakage.
- `test_scan_extra_entities_additive` — `scan(text, extra_entities=("PERSON",))` records
  `DEFAULT_PRESIDIO_ENTITIES + ["PERSON"]` (order-preserving).
- `test_scan_extra_entities_dedup` (**additivity/dedup**) — `extra_entities=("EMAIL_ADDRESS",)`
  (already in base) records the base with no duplicate `EMAIL_ADDRESS`, unchanged order.
- `test_scan_does_not_mutate_self_entities` (**concurrency invariant, Decision 6**) — after
  `scan(text, extra_entities=("PERSON",))`, `scanner._entities == list(DEFAULT_PRESIDIO_ENTITIES)`.
- `test_scan_unknown_extra_threads_through` (**Presidio-is-the-filter pin**) — `scan(text,
  extra_entities=("NOT_A_REAL_ENTITY",))` records `DEFAULT_PRESIDIO_ENTITIES + ["NOT_A_REAL_ENTITY"]`
  passed to `analyze`. Pins that the wiring does not silently drop unknown names (filtering is
  Presidio's job, per the Design note), so a regression can't hide behind a swallowed entity.

Pipeline-threading pins (backend-free) using a recording subclass so `isinstance(s, PresidioScanner)`
holds:

```python
class _RecordingPresidio(PresidioScanner):
    def __init__(self) -> None:
        super().__init__()
        self._rec = _RecordingAnalyzer()
        self._analyzer = self._rec
        self._loaded = True
```

- `test_pipeline_passes_profile_extras_to_presidio` — `Pipeline([MinimalScanner(), _RecordingPresidio()])`;
  `await inspect(text, profile="customer_service")` records base ∪ `{PERSON, EMAIL_ADDRESS, PHONE_NUMBER}`
  (order-preserving, deduped).
- `test_pipeline_no_profile_uses_base` (**negative pin at the pipeline layer**) —
  `await inspect(text)` (no profile) records exactly the base; no profile leakage.
- `test_pipeline_general_profile_empty_extras_uses_base` (**empty-extras pin — the most common
  live path**) — `await inspect(text, profile="general")` records exactly
  `list(DEFAULT_PRESIDIO_ENTITIES)`. This pins the *active-profile-with-`()`-extras* branch
  (keyword present but empty), which is structurally distinct from the no-profile branch
  (keyword omitted) and is what runs whenever `general` is the active/default profile.

### Real-backend contract — non-skipping on `extras-presidio` (`@requires_presidio`), in `tests/test_presidio_entity_scoping.py`

```python
@requires_presidio
class TestProfilePresidioScoping:
    def test_person_fires_under_customer_service_not_general(self) -> None:
        ...
```

- **The load-bearing test.** Build `Pipeline([MinimalScanner(), PresidioScanner()])`. Use a
  concrete, NER-friendly corpus with a full name and a strong contextual cue so spaCy
  `en_core_web_lg` scores `PERSON` comfortably above the 0.35 default threshold — pin the
  sentence, do **not** defer phrasing (PERSON is spaCy-NER, not a deterministic pattern
  recognizer, so a bare "John Smith" can fall below threshold and flake). Proposed corpus:
  `"Customer name: Dr. Margaret Thompson called about her account."` The implementer must
  verify the score margin on a presidio-equipped env (the Hermes venv or the CI lane) before
  the gate, and may assert `confidence > 0.45` (a buffer above 0.35) in addition to presence,
  so a marginal future model regression fails loudly rather than flaking. Assertions:
  `inspect(corpus, profile="customer_service")` yields a `petasos.presidio.person` finding;
  `inspect(corpus, profile="general")` yields **none**. This is the exact assertion PET-117
  declined to add (it would have false-greened while the field was inert) and it fails if the
  wiring ever regresses. (Fallback if `PERSON` proves unstable on the lane's model: assert
  additivity via another opt-in entity — but PERSON-under-`customer_service` is the brief's
  named contract, so keep it as the primary.)
- (Optional companion) `test_admin_person_fires` — same shape under `profile="admin"`.

### Regression / guard coverage (existing suites)

- `tests/test_profiles.py` — unchanged and must stay green (parsing/merge/validation of
  `pii_entities_extra` is untouched; the field is now *consumed*, not redefined).
- `tests/test_ci_extras_lanes.py` — must stay green with the new `NONSKIPPING_LANES` row and
  the widened `paths:` (the meta-test checks install+pytest+arm, not the `paths:` list).
- `tests/test_pipeline.py`, `tests/test_presidio_scanner.py` and the broader suite — full run
  to confirm the widened `scan`/`_scan_one` signatures and the new module import break nothing
  (and `_validate_scanner` still accepts `PresidioScanner`).
- **Pre-implementation grep (implementer):** confirm no existing test builds a real
  `PresidioScanner` under `customer_service`/`admin` and asserts the *absence* of a `PERSON`
  finding (none found at spec time; re-verify before the gate so making the field live can't
  silently break a stale expectation).

## Test command

Authoritative gate (runs locally on the project interpreter; the `@requires_presidio` real-
backend tests self-skip where presidio + `en_core_web_lg` are absent — they are enforced
non-skipping in the `extras-presidio` CI lane):

```bash
python -m pytest tests/ -k "not test_default_ignorable_rejected"
ruff check .
ruff format --check .
mypy --strict .
```

`test_default_ignorable_rejected` is deselected per the known local Unicode-13-vs-14
pre-existing failure on the 3.10 dev interpreter (unrelated to this change).

Real-backend contract (the `extras-presidio` lane, or any env with presidio + the spaCy
model installed — e.g. CI ubuntu; not the local Windows box). bash form:

```bash
PETASOS_REQUIRE_PRESIDIO=1 python -m pytest \
    tests/test_presidio_entity_scoping.py tests/test_presidio_scanner.py -v --tb=short
```

## Done when

1. `profile.pii_entities_extra` drives per-profile Presidio entity selection, additive over
   the config-resolved set, via Approach (A); the dead-config gap is closed.
2. A test pins the contract and **fails if a profile-set PII entity silently no-ops again** —
   the `PERSON`-under-`customer_service` (vs `general`) real-backend integration test — plus
   the negative pin (no-profile/default → base set) and the additivity/dedup pins.
3. The Presidio-lane real-backend tests run non-skipping under `PETASOS_REQUIRE_PRESIDIO=1`
   (PET-106 pairing intact, new row armed); `ci.yml` stays ML-free.
4. `python -m pytest` (gate command), `ruff check`, `ruff format --check`, `mypy --strict` all
   green.
5. Default-profile / no-profile detection is unchanged (negative regression pin green;
   PET-109's tightened band and noise posture preserved).
6. Decision record present: Approach A vs B vs C, the opt-in-only scope, the
   `self._entities`-as-base choice (Decision 3), and the built-in-list audit (Decision 5);
   consistency with PET-117's frozen-profile entity edit + typo guard confirmed (HEAD `bdfe8dc`).
7. After merge: `/wiki-after-merge <sha>` (and `/wiki-state-update petasos` if a state flip
   applies).

## Out of scope

- **Per-profile scope-*out* (opt-out of a default entity).** Needs a new field; this ticket is
  additive opt-in only.
- **Egress / direction-scoped PII (outbound-sink-only).** The PET-112 / PET-113 (`agent_owner`)
  guard-layer concern, distinct from making this detector-layer field live.
- **The dead `EMAIL → EMAIL_ADDRESS` string fix and its parse-time typo guard** — owned by
  PET-117 (already merged at HEAD `bdfe8dc`; prerequisite satisfied).
- **Broader Presidio entity / threshold tuning** — owned by PET-109.
- **Profile description copy** — owned by PET-113.
- **Frontend-binding metadata for the now-live field** (valid-entity-name surfacing in the
  dashboard) — brief "Other implications"; file against the console area if not covered by
  PET-113. Not in this ticket.

## Post-green polish

Folded after the spec went green at round 1 (bounded clarifications only — no behavior, scope,
or Decision/Out-of-scope/Done-when changes):

- edge-cases/F-1 (P2, *Pre-ship recommended*) — added `test_pipeline_general_profile_empty_extras_uses_base`
  to the Test plan (pins the active-profile-with-`()`-extras branch, the most common live path).
- edge-cases/F-4 (P2) — pinned a concrete NER-friendly corpus + score-margin guidance for the
  load-bearing real-backend test (removed the "tune phrasing" deferral).
- edge-cases/F-2 (P2) — Design note: unknown custom extras are deliberately not filtered
  (Presidio is the filter); added `test_scan_unknown_extra_threads_through`.
- edge-cases/F-3 (P2) — Design note: non-str retained entries are the merge path's pre-existing
  contract; `dict.fromkeys` tolerates hashable non-str; the `_scan_one` envelope covers a
  future strict-Presidio raise.
- edge-cases/F-5 (P3) — added the "Interaction: Stage-9 anonymization" note (PERSON now
  anonymized under customer_service/admin with anonymize-all default — intended).
- correctness/F-1, F-2 (P3) — corrected line anchors (Stage-4 fan-out `:618-623`; plugin_api
  ctor `:109-114`).
- correctness/F-3 (P3) — added the order-preserving caveat (custom-merged extras are set-ordered
  upstream) as a Design note; order-asserting tests scoped to built-ins.
- conventions/F-1 (P3) — reworded the Presidio special-case description (per-call concrete-type
  check; rationale stated).
- conventions/F-2 (P3) — added the mypy/protocol rationale as a code comment in the `_scan_one`
  snippet.
- conventions/F-3 (P3) — added the "Two opt-in surfaces (config base + profile additive)" note.

## Deferred (P2+)

Advisory items not folded (out of 2g's clarification scope — each is a behavior call,
over-coverage, or a separate observability concern):

- edge-cases/F-3 (option b) — *defensively coerce/skip non-str extras in `_effective_entities`*:
  a behavior change beyond clarification. Current posture (Presidio is the filter; `_scan_one`
  envelope catches a downstream raise) is documented and accepted. Revisit only if a future
  Presidio version makes non-str members raise commonly.
- edge-cases/F-2 (option) — *intersect extras with `KNOWN_PII_ENTITIES` at scan time*: a
  behavior change; the merge-time warning already flags unknowns. Deliberate non-goal here.
- edge-cases/F-6 (P3) — *backend-free circuit-breaker pin for the threaded Presidio path*:
  over-coverage. The breaker logic is unchanged (the kwargs build is outside the timed
  `wait_for`); implementer may add a pin if cheap.
- edge-cases/F-7 (P3) — *runtime DEBUG tripwire/log in `_effective_entities`*: an observability
  addition (behavior). CI is the contract net, and the `paths:` trigger now includes
  `pipeline.py`, narrowing the lane-bypass gap. Implementer may add a DEBUG log when extras are
  non-empty if it aids debugging; not required for the gate.
