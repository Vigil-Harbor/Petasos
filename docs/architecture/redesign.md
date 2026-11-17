# Petasos redesign: contracts

Status: draft for build. Branch `arch/redesign`. Targets the release after 0.5.0.

This document fixes the interfaces the redesign is built against. Work packages
in section 12 are briefed from it. Where it contradicts `CLAUDE.md` or older
docs, this document wins until those are rewritten (package D2).

Section 7 (Hermes binding) rests on `docs/architecture/hermes-host-facts.md`,
which records what upstream Hermes `v0.23.1` does when its plugin loader and
hook dispatcher are run in a sandbox. `tests/hermes_host/` is the harness
that produced it. Two things were not run there and stay open: a live
gateway and a kanban worker (section 7.6).

## 1. What Petasos is

A security layer for Hermes Agent with one configuration surface that composes
whatever scanners are installed. A non-technical user answers three questions.
A technical user can override any field. Both write to the same place and both
are validated by the same schema.

Petasos is also usable as a plain Python library (`Pipeline`, `PetasosConfig`),
but the Hermes integration is the product and ships in the wheel.

### Principles

1. **Declare once, derive everywhere.** A fact (a field, a default, a bound, a
   scanner id, a severity order) is written in one place. Validation, the
   console editor, the Hermes settings form, and the reference docs are
   generated from it.
2. **One vocabulary.** A user picks a *role* and a *level*. "Profile" means a
   Hermes profile and nothing else. "Preset", "posture" and "tier" as names for
   config bundles are retired.
3. **The library owns policy; adapters own plumbing.** Anything that decides
   whether a tool call proceeds lives in the library and is testable without a
   host.
4. **Subtract first.** Code with no consumer is deleted, not parked. Git keeps
   history.
5. **Native to the host.** Petasos should feel as if it had always been part
   of Hermes, the way the kanban board does. It uses what Hermes already has
   (its settings, approvals, redaction, dashboard, plugin hub, install and
   doctor commands) and fills the gaps Hermes leaves, chiefly tool calls and
   egress. Where Hermes owns something, Petasos defers to it. Upstream moves
   fast, so every dependency on Hermes goes through one small seam, and
   nothing Petasos ships cuts across how Hermes expects a plugin to behave.
6. **One or two choices, then proof.** A casual user sets it up with one or
   two choices on well-calibrated defaults, and no description should make
   them feel they need to be a security engineer to read it. A technical user
   can see and change everything, and can prove a change does what they meant
   in the scanner playground straight away.
7. **Readable on inspection.** Someone deciding whether to install it can open
   a module and see that it does what it says.
8. **The guarded cannot move the guard.** See `guardrail-integrity.md`.

### Invariants carried over unchanged

- The pipeline never raises; errors are returned in `PipelineResult`.
- `fail_mode` defaults to `degraded`. The syntactic scanner always runs.
- Tier 3 has a hard floor of 30.0 that no layer or override can lower.
- Structural rules cannot be suppressed or downgraded by any layer or override.
- Base install has zero third-party dependencies. (True again once the license
  code and its `pyjwt` dependency are removed.)
- Built-in roles, levels, rules and defaults are immutable.
- Latency budgets: syntactic-only under 5 ms, one ML scanner under 100 ms, full
  pipeline under 250 ms on CPU; the measured ingestion and Semgrep exceptions
  stand.
- Each scanner extra has a paired CI lane that runs its real-backend tests.

## 2. Package layout and dependency rule

```
petasos/
  __init__.py        public API (section 9)
  __main__.py        python -m petasos
  model.py           scanner protocol, findings, results, Severity and rank
  coverage.py        immutable scanner coverage metadata
  limits.py          shared examination ceiling
  normalize.py
  profile_lint.py    local-inference endpoint predicate
  config/
    schema.py        declaration, coercion, validation, description, live apply
    sections/        root, rules, scanners, session, tools
    layers.py        roles, levels, Settings, resolve(), Resolved
    floors.py  secrets.py  migrate.py
  scanners/
    registry.py      ScannerSpec, REGISTRY, compose()
    prompt_guard.py  presidio.py
    minimal/
      scanner.py     rule-family orchestration
      injection.py  command.py  role_switch.py  agent_directive.py
      structural.py  encoding.py  decode.py  views.py  taxonomy.py
    semgrep/
      adapter.py  engine.py  process.py  runtime.py  source.py  roots.py
      qualification.py  qualification.json  rules/
  session/
    frequency.py  escalation.py  audit.py  alerting.py  lineage.py  taint.py
    safe_json.py
  pipeline/
    pipeline.py      orchestration
    findings.py      merge, suppression, floors, safe computation, coverage
    health.py        timeouts, circuit breaker, scanner health
    ingest.py        bounded ingestion-result scan through the pipeline
  guard/
    guard.py         the evaluate ladder and state owner
    tools.py         tool classification data and derived sets
    params.py  selfmod.py  fanout.py
    guardrail.py     recognition dispatch
    surface.py       host surface types and library command rules
    paths.py         protected-path matching
    shell.py  shell_parse.py  mutations.py  program.py  bounds.py
  enforce/
    enforcer.py      host-facing API
    core.py  calls.py  results.py  observe.py  engine.py  runtime.py  book.py
    types.py  decisions.py  fallback.py  approvals.py  events.py
    messages.py  guardrail.py
  hermes/
    plugin.py        register(ctx): hook wiring and translation
    home.py  host.py  target.py  settings.py  guardrail.py  semgrep_host.py
    manifest.py  install.py  wheel.py  environment.py  dependencies.py
    managed.py  pinning.py
    commands.py      command dispatch, reached through cli.py
    config_set.py  migrate_cmd.py  pin_cmd.py  scanners_cmd.py
    doctor.py  doctor_advice.py  doctor_environment.py  doctor_install.py
    doctor_model.py  doctor_pin.py  doctor_render.py  doctor_report.py
    doctor_settings.py  doctor_support.py
    dashboard/       the Petasos tab's response API
  cli.py             the petasos script entry; commands live under hermes/
```

Each package has an `__init__.py` declaring its public names in `__all__`.
Imports point one way (siblings on one level may import each other):

```
model, coverage, limits, normalize, profile_lint < config < scanners, session < pipeline < guard < enforce < hermes < cli
```

Only `hermes/` binds to Hermes. The existing guard fallback is the explicit
exception: `guard/selfmod.py` lazily imports `hermes.home` when a caller has
not supplied protected paths, and `guard/guard.py` imports its resolution type
only for type checking. Keeping that fallback preserves plain-library callers.
The adapter supplies paths in normal operation. `tests/test_architecture.py`
checks the dependency direction and pins those two exceptions.

There is no standalone `console/`; the UI is served by Hermes's dashboard.
The front-end resources stay in `hermes-plugin/petasos/dashboard/`.
The script entry remains `cli.py`, while its implementation is
`hermes/commands.py`. Ingestion scanning belongs to `pipeline/` because it
calls the pipeline; `session/` contains only the lower-level session helpers.
`limits.py` remains shared by scanners, ingestion, and enforcement, so it is
not a removal candidate.

No module name starts with an underscore (apart from Python's `__init__.py`
and `__main__.py`). A package's public names are what its `__init__.py` lists
in `__all__`.

## 3. Config schema

### 3.1 Declaration

Config is a tree of frozen, slotted dataclasses declared with `@section`.
Every field uses `setting()`:

```python
@section
class EscalationConfig:
    enabled: bool = setting(default=True, help="Raise enforcement as a session keeps misbehaving.")
    tier1: float = setting(default=15.0, gt=0, help="Risk score at which tier 1 starts.")
    tier2: float = setting(default=30.0, gt=0, help="Risk score at which tier 2 starts.")
    tier3: float = setting(
        default=50.0, ge=TIER3_FLOOR, help="Risk score at which the session is terminated."
    )

    def check(self) -> None:
        if not self.tier1 < self.tier2 < self.tier3:
            raise ConfigError("tiers must be strictly ascending")
```

`@section` is a dataclass transform with `kw_only_default`. The class stays a
real frozen slotted dataclass (`kw_only=True`), so `dataclasses.fields`,
`dataclasses.replace`, and equality behave normally. `replace` builds a new
instance and therefore re-validates. mypy sees the generated constructor and
requires every setting by name. Direct construction and `from_mapping` coerce
and validate the same way and raise `ConfigError`. A positional call raises
`TypeError` and names the settings, so adding or reordering fields cannot
silently change a call.

`setting(*, default, help, ge=None, gt=None, le=None, lt=None, restart=False, audience="advanced", normalize=None)`
returns a `dataclasses.field`. Its metadata holds a `FieldSpec` under the
`FieldSpec` key. `default` is keyword-only: a type checker only treats a
keyword named `default` as the field's default. No third-party library is
involved.

| Argument | Meaning |
|---|---|
| `help` | One plain-language sentence. Required. Shown in every UI and in the docs. |
| `ge` `gt` `le` `lt` | Numeric bounds. On a mapping of numbers, the bounds apply to each value. |
| `restart` | True when a change needs a process restart to take effect. |
| `audience` | `basic`, `advanced`, or `expert`. Controls which UIs show the field. |
| `normalize` | Optional per-item function for a list of text, such as `str.upper`. |

A list, set, or bytearray default is rejected. A dict default is copied into a
read-only mapping, so the caller's dict is not shared. Defaults are checked
when the class is defined, and so is `check`. An annotation outside the
vocabulary below is a `TypeError` at class definition. Annotations are
resolved from the globals of the module that defines the section, even though
modules use `from __future__ import annotations`. A name imported only under
`TYPE_CHECKING` is not visible there. Definition then fails with `TypeError`
and tells you to import that name at runtime.

Rules the engine applies from the annotation:

- `bool` accepts only `bool`. `int` and `float` never accept `bool`.
- `int` accepts only `int`. `float` accepts `int` or `float` and stores a
  `float`. Numbers must be finite.
- `Literal[...]` accepts only its members, matched by type and value. A value
  that differs only by case is rejected.
- `tuple[str, ...]` rejects a bare string, accepts a list or a tuple, trims
  each item, rejects an empty item, and then applies `normalize`.
- `Mapping[str, float]` and `Mapping[str, str]` accept a mapping, trim keys,
  reject an empty or repeated key, and store a read-only mapping.
- `X | None` accepts `None`.
- A `@section` field is a nested section. A mapping is read as that section.
  An instance of that exact class is accepted.

`check(self)` is optional and runs only after that section's own fields have
succeeded. Raise `ConfigError("message")` for the section as a whole, or
`ConfigError.at("relative.path", "message")` for a path relative to the
section. The engine prefixes that path when the section sits inside another.
A nested section whose fields failed does not run its own `check`, and a
parent does not run `check` when any of its fields failed. Nothing else
validates config: no hand-written `__post_init__`, no parallel metadata table.

### 3.2 Engine API (`petasos.config.schema`)

```python
def from_mapping(cls: type[T], data: Mapping[str, Any]) -> T
def to_mapping(obj: object) -> dict[str, Any]
def describe(cls: type) -> tuple[FieldInfo | SectionInfo, ...]
def merge(base: Mapping[str, Any], layer: Mapping[str, Any]) -> dict[str, Any]

class ConfigError(ValueError):
    errors: tuple[tuple[str, str], ...]     # (dotted path, message)

class FieldInfo:  # frozen
    path: str
    type_name: str          # bool, int, float, str, choice,
                            # tuple[str, ...], mapping[str, float], mapping[str, str]
    default: Any            # JSON-serialisable
    choices: tuple[Any, ...] | None
    ge: float | None
    gt: float | None
    le: float | None
    lt: float | None
    help: str
    audience: Literal["basic", "advanced", "expert"]
    restart: bool
    nullable: bool

class SectionInfo:  # frozen
    path: str               # dotted path of the section field
    help: str               # the setting() help on that field
    audience: Literal["basic", "advanced", "expert"]
    restart: bool
    nullable: bool
```

- `from_mapping` is strict. An unknown key is an error. Its path is the key,
  and the message names the key and, when one is close, the nearest valid key.
  Every problem in the document is reported together. Unknown keys are listed
  first, then each field's problems in declaration order.
- `to_mapping` returns plain JSON-serialisable data: lists for tuples, dicts
  for mappings and sections. `from_mapping(cls, to_mapping(x)) == x` for every
  valid `x`.
- `describe` returns one `SectionInfo` per nested section and one `FieldInfo`
  per leaf, in declaration order. A section row appears immediately before
  that section's own rows. Its `path` is the dotted path of the section
  field and its `help` is the text declared on that field. The root has no
  row; it is the class passed to `describe`. A direct child of a section is
  a row whose path is that section's path plus one dotted name, so the flat
  result rebuilds the tree. Leaf defaults are the values a fresh instance
  carries, so an override baked into a nested default is visible. `choices`
  is set only for a `choice`. These records are enough for a settings form,
  including group headings, and a reference table.
- `leaves` returns only the `FieldInfo` rows of `describe`, for callers that
  need every setting and no headings.
- `merge` deep-merges partial documents and does not validate them. A missing
  key keeps the base value. An explicit `None` in the layer replaces the base
  value, so a layer can clear an optional setting. When both values are
  mappings they merge key by key; an empty mapping adds and removes nothing.
  Every other value, including a list, replaces the base value. The result
  shares no list or mapping with either input.

### 3.3 The tree

`PetasosConfig` is the root. Every section lives in the config layer,
including the per-scanner ones: the scanner layer sits above config and reads
its own section from the tree (section 5). The config layer imports nothing
from scanners.

```
fail_mode            open | degraded | closed
direction            inbound | outbound      default direction when a caller gives none
normalization        nfkc, zero_width, homoglyphs, decode_payloads
scanners
  timeout_seconds, breaker_threshold, breaker_cooldown_seconds
  prompt_guard       enabled, threshold
  presidio           enabled, entities, entities_extra, score_threshold, language
  semgrep            enabled, engine_path, engine_sha256, request_timeout_seconds, max_source_bytes
rules
  suppress           rule ids to drop
  severity_overrides rule id -> severity
  confidence_floor
  injection_floor_scope   all | inbound
anonymization        enabled, entities, mode
frequency            enabled, half_life_seconds, weights, rolling_window_seconds, rolling_threshold
escalation           enabled, tier1, tier2, tier3
tools
  enabled, dangerous_posture (block | approve), exempt, aliases, delegate_names
  self_change (approve | never), self_change_minutes (1 to 1440, default 30)
  lineage            enabled, max_depth, max_edges, edge_ttl_seconds
  fanout             enabled, max_per_window, window_seconds
egress               sink_tools, taint_namespaces, taint_min_span_length
audit                enabled, verbosity, emit_findings
alerting             enabled plus the fourteen existing thresholds, unprefixed
sessions             max, ttl_seconds, max_new_per_minute, max_tombstones
startup              wait_seconds
```

Changes from the 0.5 flat config:

- The profile-only levers (`suppress_rules`, `severity_overrides`,
  `confidence_floor`, `injection_floor_scope`, `dangerous_tool_posture`,
  `tool_exempt_list`, `tool_alias_map`) are ordinary fields. `ResolvedProfile`
  and `ProfileResolver` are deleted.
- `detect_rtl_override` and `fold_leet` are deleted. Neither flag changes
  `normalize()`'s `.normalized` string: RTL detection is a side flag, and leet
  folding is a match-only view. The pipeline keeps only `.normalized` for the
  optional scanners, and the syntactic scanner folds and detects on its own.
  B2 compared `Pipeline` results for all 1,955 texts in
  `tests/parity/corpus.json`, inbound and outbound, with each flag on and off.
  No verdict changed. `normalize()` keeps its own keyword arguments for direct
  callers.
- `Pipeline.inspect` loses its per-call `profile` argument. A pipeline is
  bound to one resolved config. If the console playground needs to preview a
  different role, it resolves a second config and builds a second pipeline
  over the same scanners.
- `disabled_scanners` and `semgrep_enabled` are replaced by per-scanner
  `enabled`.
- `profile_name` is replaced by `role` (section 4), which is not part of the
  tree.
- A `rules` entry that reaches a floor is an error. `rules.suppress` may not name a structural or
  self-modification rule, and may name an injection rule only when
  `rules.injection_floor_scope` is `inbound`. `rules.severity_overrides` may
  not target a structural rule at all. A self-modification rule may not be set
  below the severity the guard or the console gives it (`config_write` and
  `console_probe` are critical, `config_ref` is high); an id with no recorded
  base cannot be retargeted. An injection override is accepted here.
  Direction-aware refusal of a downgrade stays in the pipeline, because it
  depends on the scan direction. The config layer recognises these families
  by rule-id prefix; a test ties the prefixes to the scanner's own id sets.
- `rules.confidence_floor` is bounded to [0, 1]. The old profile parser
  accepted any number.
- `scanners.presidio.entities` and `entities_extra` must name a recognizer in
  the curated known set, the same set the profile parser checked for
  `pii_entities_extra`. The old flat `presidio_entities` accepted any token.
  An empty `entities` list is rejected; leave it unset for the curated default.
  `entities_extra` is where the profile field `pii_entities_extra` lands. The
  pipeline passes that list to Presidio as extra detection types. It is not
  copied into `anonymization.entities`, which remains the old `pii_entities`
  filter: empty means hide every reported type.
- `frequency.weights` keys follow the tracker's glob rule: a `*` is allowed
  only as a terminal `.*`. The old config accepted a bad glob and failed later,
  when the tracker was built. `None` means the built-in weights. An empty
  mapping means findings add nothing.
- Escalation tiers must be strictly ascending, and tier 3 cannot go below 30.
  Tier 1 has no positive lower bound. A zero tier 1 still validates when the
  three scores ascend, as it does today.
- Hash mode without a hash key is not rejected here. That check stays where
  config meets `Secrets` (section 3.4).
- An alias value is trimmed. An alias may not point at an exempt tool.
- Everything under `scanners.prompt_guard`, `scanners.presidio`, and
  `scanners.semgrep` is `restart`. The timeout and the circuit breaker are
  not: the pipeline reads them on each scan. Alerting thresholds, session
  caps, lineage bounds, and the circuit breaker are `expert`. Nothing in the
  tree is `basic`.

Components keep the config they are given; they do not copy it. The tree is
immutable all the way down (frozen slotted sections, tuples, read-only
mappings, and a fresh set of nested sections per instance), so there is
nothing a well-behaved caller can change afterwards. The old pipeline copied
its flat config on intake. A copy only defends against code that deliberately
writes past the frozen guard, and such code can reach the component's own
copy just as easily.

### 3.4 Secrets

`session_secret` and `hash_key` are not config. They live in
`Secrets(session_secret: bytes | None, hash_key: str | None)`, which the host
loads from the environment and passes beside the config. `Secrets` has no
`to_mapping` and a redacting `repr`. Rules that span both (hash mode needs a
hash key) are checked where the two meet, in `Pipeline` and `Enforcer`
construction.

### 3.5 Live changes

`reconfigure(new)` on `Pipeline` and `Enforcer` applies every changed field
whose spec is not `restart` and returns the paths it could not apply:

```python
@dataclass(frozen=True)
class ReconfigureResult:
    applied: tuple[str, ...]
    restart_required: tuple[str, ...]
```

Everything under `scanners.<id>` is `restart` in the first cut. One field
should not stay that way: `scanners.presidio.entities_extra` is what roles
set, and today the equivalent profile list is passed to Presidio on each scan,
so a profile switch takes effect live. B4 keeps that by passing the field per
scan and marks it live. A change that
needs a restart is always reported, never silently ignored.

## 4. Layers: role and level

What a user writes is a `Settings` document:

```yaml
enabled: true
role: research
level: balanced
overrides:
  scanners:
    presidio: {score_threshold: 0.3}
```

```python
@dataclass(frozen=True)
class Settings:
    enabled: bool = True
    role: str = "general"
    level: str = "balanced"
    overrides: Mapping[str, Any] = {}

@dataclass(frozen=True)
class Resolved:
    settings: Settings
    config: PetasosConfig
    origin: Mapping[str, str]      # dotted path -> "default" | "role" | "level" | "override"

def resolve(settings: Mapping[str, Any] | Settings) -> Resolved
```

Resolution is `defaults <- role <- level <- overrides`, each a partial document
merged with `schema.merge`, then validated once by `from_mapping`. `origin`
lets any UI say where a value came from. "Custom" is not stored: it means
`overrides` is non-empty.

`enabled` is the arm switch. It is read live and is not part of
`PetasosConfig`.

### 4.1 The two axes cannot collide

A role may set only: `rules.*`, `tools.dangerous_posture`, `tools.exempt`,
`tools.aliases`, `tools.self_change`, `scanners.presidio.entities_extra`.
`tools.self_change_minutes` is not on either axis. `support` sets
`tools.self_change` to `never`.

A level may set only: `fail_mode`, `escalation.tier1..3`,
`scanners.presidio.score_threshold`, `anonymization.enabled`.

A test asserts the two sets are disjoint and that every built-in stays inside
its set. Merge order between role and level therefore never matters.

### 4.2 Built-ins

Roles, replacing the five profiles:

| Role | Was | Sets | Suggests |
|---|---|---|---|
| `general` | general | dangerous posture `approve` | balanced |
| `coding` | code_generation | suppressions for code-shaped text, confidence floor 0.6, PromptGuard injection downgraded, injection floor scoped to inbound, dangerous posture `approve` | balanced |
| `research` | research | encoding suppressions, confidence floor 0.7 | relaxed |
| `support` | customer_service | injection openers raised to critical, extra PII entities | balanced |
| `admin` | admin | extra PII entities PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE | strict |

`research` and `admin` no longer carry tier thresholds; the suggested level
carries that intent. Those thresholds never took effect in Hermes, because the
plugin did not pass a profile to the guard. A role's suggestion is shown as a
recommendation and is never applied automatically.

Levels, replacing the five metals with the three that were distinct in
practice:

| Level | Was | fail_mode | tiers | presidio threshold | anonymize |
|---|---|---|---|---|---|
| `relaxed` | Bronze | degraded | 25 / 45 / 65 | 0.50 | off |
| `balanced` | Iron (defaults) | degraded | 15 / 30 / 50 | 0.35 | off |
| `strict` | Steel | closed | 10 / 22 / 40 | 0.30 | on |

Tin (fail-open, tool guard off) and Titanium are reachable through `overrides`
and are not named levels. `balanced` equals the schema defaults field for
field; a test asserts it. Each level document names all six of its fields,
including a value that equals the default, so `origin` says `level` for those
fields.

Roles and levels are frozen data in `layers.py`. Custom named profiles are
dropped: a role plus `overrides` covers the case, and nothing outside tests
registered one.

### 4.3 Migration

`petasos config migrate` reads a 0.5 flat `petasos:` section and prints the
equivalent `Settings`. The library function is `migrate` in
`petasos.config.migrate`. The command-line wrapper is a later package. There
is no runtime support for the old format.

`profile_name` becomes `role`, using the rename in section 4.2. A missing
profile, or an explicit null, is `general`. An unknown profile is dropped, and
the note names the roles. The general role asks before a risky tool call. A
configuration converted as general did not: the old profile blocked. Migration
writes `tools.dangerous_posture: block` for that configuration, unless the old
section already names `dangerous_tool_posture`, and the note says why. An
upgrade does not start asking on its own.
`enabled` becomes
`Settings.enabled`. `host_id` is dropped; the host supplies it beside the
config.

Level-owned fields, with absent keys read as today's defaults, are compared
with the three levels. An exact match becomes `level`. Anything else stays
`balanced`, and the values that differ become overrides. A migrated default
install, and a Bronze, Iron, or Steel section, therefore has empty
`overrides`. Tin and Titanium do not match a level. Their differences are
overrides.

A value that is present in the old section and still differs from what that
role and level resolve to becomes an override, and nothing else does. One
exception: `presidio_entities_extra` and the profile's `pii_entities_extra`
were both additive detection lists. Migration unions them into
`scanners.presidio.entities_extra`, flat names first, so neither source is
dropped. An absent flat list leaves the role's list in place and writes no
override.

`disabled_scanners` and `semgrep_enabled` become the per-scanner `enabled`
values. A listed `prompt_guard` or `presidio` is `off` (the default is
`auto`). `semgrep_enabled: true` is `on`, unless `semgrep` is also disabled,
in which case disabled wins and the value stays `off`. `llm_guard` and
`llama_firewall` are dropped with a note. Any other unknown id is dropped
with a note.

`detect_rtl_override`, `fold_leet`, `session_secret`, and `hash_key` are
dropped. The note for a secret names the environment variable and does not
include the value. Unknown keys are dropped with a note.

The `research` and `admin` profiles carried tier thresholds (25/45/70 and
10/20/35) that the new roles do not. Those numbers are not copied. The Hermes
plugin constructs `ToolCallGuard` without a profile, and pipeline escalation
reads the config tiers, so the profile numbers never changed enforcement
there. Migration adds a note naming the old numbers and the suggested level
(relaxed 25/45/65, strict 10/22/40). Explicit tier fields in the flat section
are ordinary level fields and are migrated with the rest.

## 5. Scanner registry

```python
@dataclass(frozen=True)
class ScannerSpec:
    id: str                          # equals Scanner.name and the key under `scanners`
    label: str
    extra: str | None                # pip extra that provides the backend
    detects: frozenset[Capability]   # "injection" | "pii" | "code"
    section: str                     # attribute under `config.scanners` holding its settings
    default_enabled: Enabled         # "auto" for prompt_guard and presidio, "off" for semgrep
    build: Callable[[Any, BuildContext], Scanner]   # receives that section instance

REGISTRY: tuple[ScannerSpec, ...]    # presidio, prompt_guard, semgrep

def compose(
    config: PetasosConfig,
    context: BuildContext,
    *,
    registry: tuple[ScannerSpec, ...] = REGISTRY,
) -> Composition

def is_registered(state: ScannerState) -> bool
def recommendations(composition: Composition, role: str | None = None) -> tuple[str, ...]
```

Every scanner section starts with `enabled: Literal["auto", "on", "off"]`:

| Value | Package installed and usable | Installed but unusable | Not installed |
|---|---|---|---|
| `auto` | `active` | `unavailable`; registered, so every scan errors and `fail_mode` applies | `not_installed`; not registered, no effect on verdicts |
| `on` | `active` | `unavailable`, as above | `unavailable`; a stand-in that errors on every scan is registered, so `fail_mode` applies |
| `off` | `off`; never constructed | `off` | `off` |

"Installed but unusable" is a backend whose package imports but whose model or
engine cannot be used: gated weights not downloaded, a load failure, a missing
engine binary. It blocks under the default fail mode on purpose. Someone who
installed a scanner meant to run it, and letting it fall away silently would
hide a broken protection. "Not installed" under `auto` is the one case that is
quiet, and it is a deliberate change: in 0.5 PromptGuard registers even when
its packages are absent, so a base install blocks everything until the
operator disables it. Scanners tell the two apart through the cause their
`availability()` probe already reports (`absent` or `load_failed`).

`Composition` holds the scanner tuple (the syntactic scanner first, always)
and one `ScannerStatus` per registry entry. `ScannerStatus` carries `id`,
`state`, `reason`, `extra`, `detects`, and `label`. `state` is `active`,
`unavailable`, `not_installed`, or `off`. `reason` is `None` only for
`active`. `extra` is the pip extra, including when the scanner is active.
This replaces the five-outcome status whose `failed` value did not say
whether a scanner was registered.

`is_registered(state)` is that rule, and it has no exceptions. `active` and
`unavailable` are in the tuple. `not_installed` and `off` are not. The reason
is not consulted. `compose` checks the rule before it returns.

`BuildContext` carries what a builder cannot get from config: the Semgrep
lifecycle owner and scheduling key. Semgrep is an ordinary registry entry.
Without a lifecycle owner the adapter is not constructed and not probed. The
status is `unavailable`, the reason is `semgrep.host_lifecycle_unavailable`,
and an `UnavailableScanner` is registered so the state and the list agree.
In 0.5 this case was left out of the list. A builder exception whose text is
`semgrep.unsupported_platform` or `semgrep.host_lifecycle_unavailable` keeps
that text. Any other exception while building Semgrep is
`semgrep.construction_failed`.

`UnavailableScanner` is the stand-in. It satisfies `Scanner`, and every scan
returns its reason and does not raise. It is registered when the backend
cannot be used and there is no working instance to keep: the package is
missing and `enabled` is `on` (including a probe result of `absent`), the
builder raises, or Semgrep was requested without a lifecycle owner. A
constructed backend whose probe reports `load_failed`, or any other unusable
cause, stays registered itself so its own scan error reaches `fail_mode`.
An `ImportError` raised by the probe is that unusable case, not "not
installed": the instance is already registered.

`compose` is the only place scanners are constructed from config. The registry
is a literal tuple: there is no third-party scanner discovery. A caller with a
custom scanner passes it to `Pipeline` directly. `registry` defaults to
`REGISTRY`. Tests pass fake specs so the enablement table does not depend on
the real backends. `compose` never raises because an optional backend failed.
A failure to construct the syntactic scanner is not caught. It reads
`normalization.decode_payloads` for that scanner.

Backend constructor knobs are reachable from config or deleted. PromptGuard's
threshold is `scanners.prompt_guard.threshold` and defaults to the same cutoff
when a caller constructs `PromptGuardScanner` with no arguments. Presidio
receives `entities`, `language`, and `score_threshold`. `entities_extra` is
not a constructor argument: the pipeline passes it on each scan as
`extra_entities`, which is what lets a role switch apply live. Semgrep
receives `engine_path`, `engine_sha256`, `request_timeout_seconds`, and
`max_source_bytes`, plus the lifecycle owner and scheduling key from
`BuildContext`. The scheduling key is stored by the adapter only once an
engine lease is acquired.

`recommendations(composition, role=None)` returns plain-language lines for
`doctor`. No active `injection` scanner suggests the `prompt-guard` extra.
Role `support` or `admin` with no active `pii` scanner suggests `presidio`.
Each `unavailable` scanner adds its reason and the fix, in registry order,
ahead of those suggestions.

## 6. Enforcement

`petasos.enforce.Enforcer` is the host-facing object. It owns the lifecycle and
the orchestration the reference plugin keeps in module globals. It does not
know which host it is running in. The pure decisions it calls live in the
same package (`decisions`, `fallback`, `approvals`, `messages`).

```python
class Enforcer:
    def __init__(self, source: SettingsSource, *, host: HostInfo | None = None,
                 events: EventSink | None = None, clock: Clock | None = None,
                 scanners: Sequence[Scanner] = (),
                 registry: tuple[ScannerSpec, ...] | None = None,
                 limits: Limits | None = None, init: InitGate | None = None,
                 evaluation: EvaluationFault | None = None,
                 spool_path: str | None = None) -> None
    def start(self) -> None                          # background init, returns at once
    def settle(self, timeout: float = 30.0) -> bool  # optional wait until init finishes
    def tool_call(self, call: ToolCall) -> Decision
    def tool_result(self, call: ToolCall, result: object) -> str | None
    def tool_finished(self, call: ToolCall, result: str = "", *, duration_ms: int = 0) -> None
    def session_started(self, session_id: str = "") -> None
    def subagent_started(self, child: str, parent: str) -> None
    def subagent_stopped(self, child: str) -> None
    def approval_requested(self, notice: ApprovalNotice) -> None
    def approval_answered(self, notice: ApprovalNotice) -> None
    def refresh(self) -> None                        # apply the current snapshot now
    def status(self) -> Status
    def session_tier(self, session_id: str) -> str | None
    def close(self) -> None                          # idempotent

Decision = Allow | Block | Approve
```

`SettingsSnapshot` carries `armed`, the resolved config tree, the secrets, a
change `token` compared with `==`, and an `error` when the observation is not
usable. `SettingsSource` is a callable returning that snapshot. The enforcer
reads it on each call. A new token is applied through `apply_live` and the
pipeline and guard reconfigure paths. Restart-only fields are left as they are
and logged. An error keeps the last good tree and logs `PETASOS_RELOAD_FAILED`.
Arming is the snapshot's switch, checked on every call.

`HostInfo` is what the host can answer: `host_id`; `approve_directive`;
`approval_grant()`, an `ApprovalGrant` whose `mode_off`, `yolo`, and `context`
flags are the combination that would grant an approve with nobody attached
(any one of them means the enforcer does not hand the host an approve it would
allow); `rule_always_approved(rule_key)`; `command_will_be_asked(command)`,
true only when the host will put that command string to a person, and false
by default; `command_checker()`, the loaded owner of terminal pipe, decode and
fetch execution or none, and `command_prompt_name`, the host prompt's display
name; `subagent_hooks`; an optional `redactor` (`None` means redaction
is unavailable); `display_path`; `protected_paths()`, the filesystem paths the
agent must not modify; and `guardrail_surface()`, the host's labelled paths and command
patterns. The guard uses the path set when it is supplied. Callers that supply
nothing keep the previous discovery. A recognised guardrail change is decided
before the rest of the ladder and can only make the outcome stricter. Under
`tools.self_change: never` it is blocked. Under `approve` it is held for a
person unless a live session grant covers it, and it is blocked when the host
would grant the approval with nobody attached or cannot ask at all. The
session grant and its time limit live on the enforcer's clock. See
`guardrail-integrity.md`.

`Limits` defaults to the plugin's deadlines: 2s to wait for initialisation,
15s for one evaluation, and 5s added to the configured scanner timeout for a
tool-result scan. `Clock` supplies monotonic time for those deadlines and for
the 30s operator-log windows. `ManualClock.advance` opens a window without
sleeping. Spool timestamps stay on the wall clock.

`init` is an `InitGate`. `held` keeps the enforcer in `starting` until
`release` or `fail`. `failed` finishes in `failed` without building a pipeline.
`skip_wait` marks the cold-start budget already spent. `evaluation` is an
`EvaluationFault` a test arms so a guard evaluation raises or does not return;
the production path leaves it disarmed.

Lifecycle is one state from `status()`: `disarmed` when the switch is off,
otherwise `starting`, `ready`, or `failed`. `starting` and `failed` use the
syntactic fallback and `fail_mode`. A call that is still waiting when
initialisation finishes, and whose syntactic scan was clean, continues on the
live pipeline. A non-clean scan stays on the fallback.

No host-facing method raises. `tool_call` turns an internal failure into
`Allow` or `Block` under `fail_mode`, with an event and a log line. A block
always has a message. `tool_result` returns `None` when the text is unchanged
or the scan fails, which is the host's signal to keep the original string. A
value that is not text is not scanned.

Threading. `start` returns immediately. The methods above may run concurrently
on the host's hook threads. Evaluation and result scans use two loops owned by
the instance, and the inspect lock serialises pipeline access. `close` stops
the loops, is idempotent, and may overlap those calls. After it returns,
further calls do not scan. Two enforcers in one process share nothing. There
is no module-level mutable state under `petasos/enforce/` except the legacy
spool helpers in `events.py`, which the plugin and the console still call.
`EventSpool(path, secret=...)` is the default sink when `spool_path` is set
and `events` is omitted. It does not touch that legacy state.

Scanner composition uses `petasos.scanners.registry.compose`. Extra scanners
are appended when their names are not already present. `auto` for a missing
package leaves the scanner out. `on` registers a stand-in that fails every
scan, so `fail_mode` applies. Operator lines use the `PETASOS_...` markers and
the logger `petasos.enforce`.

The modules are `enforcer` (the public object), `core` (lifecycle and
settings), `calls` (the tool-call decision), `results` (result scan and taint),
`observe` (session, sub-agent, and approval records), `engine` (compose and
live apply), `runtime` (the two loops), `book` (counters and log windows),
and `types` (the values above). The decision functions stay where package C1a
put them.

## 7. Hermes binding

Target host: upstream Hermes Agent `v0.23.1` or later. There is no
compatibility path for the older 0.18 fork, which has no plugin settings API.

### 7.1 Shape

Petasos reaches Hermes as a **directory plugin in front of the wheel**:

```
<HERMES_HOME>/plugins/petasos/
  plugin.yaml      generated from the schema by petasos.hermes.manifest
  __init__.py      one line: from petasos.hermes.plugin import register
  pyproject.toml   depends on the petasos wheel
```

All behaviour is in the wheel. The directory carries no logic, so it cannot
drift in any way that changes enforcement. Two host rules shape it. The
manifest must carry `name`, `version`, `description` and a `provides_hooks`
entry for every hook `register()` registers, or `hermes plugins validate`
fails. And `__init__.py` stays a bare import: Hermes guesses a plugin's kind
by scanning that file's text, and certain words in it would take the plugin
out of the general loader. It exists because Hermes renders a
settings form, checks `requires_hermes`, and records an install only for
directory plugins; a pip entry point gets none of those. Petasos registers no
entry point: one discovery path.

`doctor` compares the installed `plugin.yaml` with what the wheel would
generate and says so when they differ.

### 7.2 Settings

The `Settings` document of section 4 is stored where Hermes keeps plugin
settings, per Hermes profile:

```yaml
plugins:
  enabled: [petasos]
  entries:
    petasos:
      settings:
        enabled: true
        role: research
        level: balanced
        overrides: {}
```

The manifest's `config_schema` declares exactly these keys. Hermes Desktop
renders `enabled` as a switch, `role` and `level` as dropdowns, and
`overrides` as a JSON text area. The schema format is flat and has no ranges
or nested shapes, which is why the basic surface is three choices and
everything else sits behind `overrides`. The two secrets are declared with
`type: secret` and an explicit `env:` name, so the form stores them in the
profile's `.env` as `PETASOS_SESSION_SECRET` and `PETASOS_HASH_KEY`. Plugin
settings calls do not reach `.env`: the adapter reads the two values with
Hermes's own env-file reader.

Rules the host imposes:

- Defaults live in Petasos. The schema's `default` is display only.
- Settings are read with `ctx.get_config` on each call, never captured in
  `register()`. Hermes sends no change notification; within one process a
  write on disk is visible on the next read. `hermes.settings` wraps
  this as the enforcer's `SettingsSource`. The change token is the four
  values plus a digest of each secret, because the enforcer applies secrets
  only when the token changes. The digest is not the secret. Re-arming to
  the same four values is not a new configuration.
- Nothing but Hermes writes `config.yaml`. The plugin uses `ctx.set_config`;
  the console and the CLI use Hermes's own writer. A plain YAML dump by another
  process has already misplaced keys once on this machine.
- Hermes expands `${NAME}` inside setting values. Petasos settings never need
  that sequence; `doctor` flags one if it appears.

### 7.3 Hooks

`petasos.hermes.plugin.register(ctx)` binds one home's `Enforcer` to the
hooks below and translates between hook arguments and `ToolCall` /
`Decision`. It contains no policy.

Hermes calls `register` from `PluginLoaderMixin._load_plugin_scoped`
(`hermes_cli/plugins_loader.py`, the `register_fn(ctx)` call). A second
`discover_and_load()` on a manager that has already loaded returns without
calling it. `discover_and_load(force=True)` unloads that manager, which
drops its hooks, then loads again and calls `register` with a new context
on the same manager. That is what `discover_plugins(force=True)` does, and
what the gateway's `reload-plugins` verb, the dashboard, and plugin
activation call. A different resolved home is a different manager:
`get_plugin_manager` (`hermes_cli/plugins.py`) keys `_plugin_managers_by_home`
by `get_hermes_home()`, and `set_hermes_home_override` (`hermes_constants.py`)
is the context-local switch a multiplexed process uses. Loading that manager
calls `register` again.

One process can therefore serve more than one profile, and each profile has
its own settings and its own enforcement state. The enforcer is chosen when
the hook runs: Hermes dispatches the manager for the active home
(`invoke_hook` goes through `get_plugin_manager`), and the callback is a
method of that home's registration. A repeated `register` for the same home
reuses the enforcer, so a reload does not rebuild it and does not reload
scanners. It binds the hooks again only when that manager no longer has
them. A second `register` on a manager that still has them does not add
another copy. `close()` stops every home's enforcer. A `register` after
that starts a new one; hooks left on a manager from before `close` fail
closed until that load replaces them.

The context object passed to `register` stays callable. `PluginContext.get_config`
(`hermes_cli/plugins_context.py`) reads `load_config_readonly()` of whichever
home is active at the call, and does not capture the home at construction.
Force reload keeps the same manager object. Keeping the context and calling
`get_config` from a hook is safe because the hook runs on the manager Hermes
selected for the active home. It is not a snapshot of the home at `register`.

Startup logs `PETASOS_ARMED_RESOLUTION` with the tier and the `config.yaml`
the call bound to. During `register` the manager's home is the context-local
override, so the path is that home's config file, which is where the plugin
settings live.

`on_profile_change` is not a Hermes hook. v0.23.1 does not list it and has
no site that fires it. Registering it only logs that the hook is unknown.
Settings for the active profile are whatever `get_config` returns on the
next call. There is no profile-change handler.

| Hook | Use | If the callback fails |
|---|---|---|
| `pre_tool_call` | The enforcement point: block, or hand to Hermes approval | An exception becomes a block. So does exceeding `plugins.hook_callback_timeout` (30 s by default), after which Hermes skips the callback for 60 s and blocks those calls outright |
| `transform_tool_result` | Annotate ingested content | Hermes passes the result through unchanged. If two plugins return text, the first registered wins |
| `post_tool_call` | Taint and audit bookkeeping | Ignored |
| `on_session_start` | Session bookkeeping | Ignored |
| `subagent_start`, `subagent_stop` | Lineage | Ignored; the fan-out budget is enforced on the `delegate_task` tool call |
| `pre_approval_request`, `post_approval_response` | Approval observation | Ignored. Neither runs when Hermes refuses an approval because nobody is attached |

Consequences for the adapter and the enforcer:

- **A block always carries a message.** Hermes ignores a block directive
  that has none, which would turn a block into an allow. The adapter refuses
  to emit one.
- **Callbacks do not raise, including `pre_tool_call`.** Hermes would turn
  an exception there into a block whose text includes the exception, which
  can echo tool arguments, and an exception in `transform_tool_result`
  fails open. The adapter returns its own block from `pre_tool_call` and
  `None` from the other hooks, and logs the exception for the operator.
- A profile whose config still has a top-level `petasos:` section is not a
  host event the adapter watches. `petasos config migrate` is the command
  that reads that section. The running plugin reads `ctx.get_config`.
- The enforcer's own time limits sit below the host's, so a slow scan becomes
  a Petasos decision under `fail_mode` and not a host timeout followed by a
  minute of blanket blocking.
- `tool_result` catches everything and always returns a string, because the
  host fails open there.
- `HostInfo.host_id` is the stable product id `petasos`. Hermes does not
  expose an installation id, and a hash of the home would change the session
  token when the profile changes.
- **What `approve` means depends on the host's state.** Hermes grants a
  plugin's approve directive without asking when `approvals.mode` is `off`,
  when yolo is on, when the process is a single-query, cron or unattended
  session whose matching mode is set to `approve`, or when the rule key is
  already on the permanent allow-list as `plugin_rule:<rule_key>`. In every
  other case with nobody attached it refuses the call. `HostInfo` reports
  which of these holds, and `doctor` says plainly when `dangerous_posture:
  approve` currently amounts to allow. A profile that sets the
  single-query and cron modes to `approve` has its scheduled work in that
  position.
- Some tool calls arrive with only a `task_id`. Session-keyed state keeps
  today's fallback.
- A plugin that failed to load enforces nothing, silently. `doctor` checks
  that the plugin is enabled and loaded, so a watchdog can call it.

Hermes offers two further fail-closed levers that Petasos does not use today:
`pre_llm_call` can block a turn, and `transform_llm_output` with
`hold_stream=True` can withhold a reply. Using them adds enforcement surface.
That is new function, not restructuring, and is left for after the redesign.

### 7.4 Self-protection

A recognised guardrail change is no longer allowed below tier 2. `tools.self_change`
is `approve` by default and `never` for the support role. `approve` holds the
call for a person, with a session-scoped rule key that expires after
`tools.self_change_minutes` (default 30, at most 24 hours). `never` refuses it.
The Hermes adapter supplies the host paths and command patterns through
`HostInfo.guardrail_surface`. Petasos's own package files and commands are
recognised in the library. The pin commands store those settings in
Hermes's machine-level config, and Petasos reads a pin whole. Redirecting
the managed directory limits what a pin can fix; see
`guardrail-integrity.md`. What the guard recognises:

- the commands `hermes plugins disable`, `enable` and `remove`, the
  `--safe-mode` flag, and `hermes gateway restart`;
- the environment variable `HERMES_SAFE_MODE`;
- the plugin directory under `<HERMES_HOME>/plugins/`;
- in the profile's `config.yaml`: `plugins.enabled`, `plugins.disabled`,
  `plugins.entries.petasos`, and `plugins.hook_callback_timeout`;
- `<HERMES_HOME>/active_profile`, which redirects the CLI.

### 7.5 Commands

- `petasos doctor`: install state, plugin enabled and loaded, manifest in
  step with the wheel, scanner states, resolved settings with origins,
  recommendations. Replaces `verify.py`.
- `petasos hermes install`: puts the plugin directory in place for a profile
  and enables it.
- `petasos hermes pin [--write]`: previews the complete plugin lists, all
  resolved Petasos settings, and the effective plugin-check timeout. With
  `--write`, writes atomically to a writable managed directory, or prepares a
  private merged document and prints only system `mkdir`/`install` commands
  for a person to run with administrator rights. Never run Petasos as root.
  The file applies to every profile using that directory. The preview names
  the limits on files, Python and the record.
- `petasos hermes unpin [--write] [--accept-profile-changes]`: removes only
  the recorded pin keys, preserving unrelated managed values. Differences in
  the profile are shown and block removal unless explicitly accepted. Uses
  the same direct-write or administrator-staging route as pin.
- `petasos config migrate`: section 4.3.
- `petasos config set <setting> <value>`: changes one simple setting through
  Hermes, with the same checks as the settings form, and says when the change
  takes effect. It exists so a `doctor` line can name a command that fixes
  the thing it reports. Lists and groups are edited in the form.
- `petasos scanner add|remove <name>`: changes which optional checks the
  plugin's environment carries.

Each is also `hermes petasos ...` inside a Hermes that has the plugin.

### 7.6 Installing

There are two install routes. The command says which one it is. Both leave
Petasos in the environment a new Hermes process activates, which is the
committed environment under `<HERMES_HOME>/installs/`, not whatever Python
happened to run the installer. A process that is already running keeps the
old environment until it starts again.

- **Released.** One command:

  `hermes plugins install https://github.com/Vigil-Harbor/Petasos.git#hermes-plugin/petasos --enable --yes-deps`

  Hermes clones the plugin directory and installs the `petasos` requirement
  in that directory's `pyproject.toml` from a package index into the
  committed environment. `--enable` and `--yes-deps` answer the two prompts
  (turn the plugin on, and allow the Python dependencies). Without them, a
  non-interactive run leaves the plugin installed and not enabled. At a
  terminal the same command without the flags asks, and answering yes is the
  same result. `UV_INDEX_URL` (or `PIP_INDEX_URL` / `index-url` in pip.conf,
  which Hermes bridges) replaces the default index. An extra index
  (`UV_EXTRA_INDEX_URL` or `PIP_EXTRA_INDEX_URL`) is searched first. uv stops
  at the first index that publishes a package name, so a package on the extra
  index is taken from there and not from the default index. A name the extra
  index does not publish falls through. A direct URL requirement is not
  installed.

- **Development.** `petasos hermes install`, and `hermes petasos install`
  once the plugin can load. This is for a build that is not the package the
  index would supply. The same version number can already be on the index
  and be a different build, so the command does not ask the index for
  `petasos`. It writes the plugin directory, including a wheel of this build,
  and a `pyproject.toml` that depends on `petasos==<this version>` with
  `[tool.uv.sources]` pointing at that wheel file. Turning the plugin on
  goes through Hermes, which installs the file into the committed
  environment. Running it again refreshes the wheel and, when the plugin is
  already on, asks Hermes to rebuild.

`petasos doctor` asks the committed environment's own Python whether it can
import a compatible Petasos. It does not trust the interpreter that launched
doctor. When that environment exists and the import fails, or the version
does not satisfy the requirement in the plugin's `pyproject.toml`, the
verdict is not protected and the next step is `petasos hermes install`.
When Hermes has not committed an environment, doctor says so and does not
treat that alone as a failure.

An optional scanner is one command, `petasos scanner add <name>` (and
`hermes petasos scanner add <name>`). `<name>` is the scanner id
(`prompt_guard`, `presidio`, `semgrep`), its label, or its extra. The
registry maps the name to the extra. The command adds that extra to the
plugin's `petasos` requirement and asks Hermes to rebuild, which is how
Hermes installs a plugin dependency. `petasos scanner remove <name>` takes
it off. Doctor's suggestion for a missing scanner is that command. The
command says to restart Hermes, and for PromptGuard it says the packages
are large and the first run downloads the model (about 1.1 GB, after the
model terms are accepted).

Enabling or disabling any plugin, installing or updating one, and a Hermes
update that syncs dependencies (`step_provision_runtimes` in
`hermes_cli/post_update.py`, and the update-completion sync) rebuild the
committed environment from the current plugin set. An enable of a plugin
that is already enabled does not. The development wheel survives a rebuild
because the path source is inside the plugin directory, which Hermes copies
into each generation. Disabling Petasos drops it; enabling it again installs
the same wheel. Deleting the installed package while the plugin files are
unchanged does not change that stamp, so the ordinary rebuild does not put
the package back. `petasos doctor` still reports that the committed
environment cannot import Petasos, and `petasos hermes install` restores
the recorded environment. Hermes refuses that restore when it is also asked
to change the plugin set, so the command calls `sync_venv` with repair and
with no plugin selection.

Still open, because no gateway was started:

- When a running gateway re-reads settings changed from the Desktop form or
  the CLI.
- Whether a kanban worker sees current settings or those from when its
  session was created.

## 8. The user-facing surface

`docs/architecture/hermes-native-fit.md` records what Hermes `v0.23.1` offers
a plugin and what Petasos should stop doing itself. This section is the
design that follows from it. The standalone console (its own local web
server, its own token, its own visual language, kept alive by the operating
system) is retired. Petasos is met through Hermes.

### 8.1 Where each piece lives

| Piece | Home | How |
|---|---|---|
| The two choices (on, role, level) | Hermes Desktop, Settings, Plugins | The manifest's `config_schema`. No Petasos code. |
| The same two choices, on the web dashboard | The Petasos tab | The dashboard does not draw `config_schema`, so the tab's first panel offers them. |
| Everything else (`overrides`) | The Petasos tab's settings panel | Built from `describe()` and `resolve()`; shows where each value came from |
| Scanner playground | The Petasos tab | Beside the settings, so a change can be tried at once |
| Activity: what was blocked and why | The Petasos tab | Reads the event spool. Hermes's Logs page is its own log and is the wrong place. |
| Health and diagnostics | `hermes petasos doctor`, and a status line on the tab | A command the plugin registers with Hermes. `hermes doctor` has no plugin row to join. |

The tab is a Hermes dashboard plugin: a manifest, a script and an API router
shipped in the plugin directory, the last two as one-line imports from the
wheel like `__init__.py`. Hermes puts plugin tabs in a Plugins group in its
sidebar, beside the kanban board.

### 8.2 Rules

- **Hermes's kit, not ours.** The tab is drawn with the components, styles
  and colour tokens Hermes exposes to plugin front ends, and follows both of
  its themes. Petasos ships no font, palette or layout shell of its own.
- **One writer.** Every settings change, from the tab, the Desktop form or
  the command line, goes through Hermes's plugin-settings writer. Nothing
  else writes Hermes's config.
- **No data of its own.** The tab's API holds no field metadata, validation,
  role or level data. It serves what `describe()`, `resolve()`, the scanner
  registry and the event spool say. The front end mirrors nothing.
- **Its own pipeline for the playground.** The dashboard is a different
  process from the gateway that enforces, so the playground builds a
  pipeline from the same resolved settings. It shows what would happen; the
  activity panel shows what did.
- **Hermes asks, Hermes redacts.** Approvals appear in Hermes's own approval
  prompt. Text shown to a person goes through Hermes's redactor.
- **Two switches, explained.** Hermes's enable list decides whether the
  plugin loads; Petasos's `enabled` pauses protection without a restart and
  records what passed while it was paused. The tab and `doctor` say which
  one is off.

### 8.3 Words

Every description a user reads is written for someone who has not heard of a
fail mode or an escalation tier, and is reviewed as copy. The technical name
follows the plain statement; it does not replace it.

### 8.4 How the interface is built

The front end is developed in a judged loop: a generator (Opus) revises the
tab, and judges (Codex) score each revision on design, usability,
conventions and fit with Hermes, each out of ten. The loop ends when every
score is 8 or higher. The judges are never told the bar, or that there is
one: they score what they see, so the number is a measurement and not a
target to be met. Every round's scores and the judges' reasons are kept, so
improvement across rounds can be read afterwards and the bar revisited. The
judges work from screenshots of the result beside reference screenshots:
Hermes's own dashboard in both themes for what native looks like, and a
well-regarded secrets manager for how a security tool presents status,
policy and an audit log. The references are kept outside the repository.

### 8.5 Overlap with Hermes, to settle separately

Hermes already detects dangerous terminal commands and gates them through
approvals. Petasos's command rules cover the same ground for the `terminal`
and `execute_code` tools, and its encoding rules overlap for shell commands.
The native-fit report recommends deferring to Hermes there and keeping
Petasos's rules for command-shaped text that never reaches those tools.
Doing that changes verdicts and what feeds the session score, so it is its
own package, decided after the order in which Hermes runs plugin hooks and
its own gate has been run and observed, not read.

One collision needs no decision: when two plugins both rewrite a tool
result, Hermes keeps the first in load order, and its bundled
`security-guidance` plugin loads before Petasos. `doctor` warns when both
are enabled.

The order has been run and the overlap measured in
`docs/architecture/hermes-command-overlap.md`. The decisions dated November
10 and November 15 in that document are what the code does. With Tirith
loaded, asking roles leave its three terminal execution rules to it; blocking
roles keep blocking.
Activity records the owner and doctor explains the split. Result annotations
are unchanged; host facts section 18 records their collision and the limits
of the earlier terminal-output hook.

### 8.6 The dashboard API

Package C3. The tab's API lives in `petasos/hermes/dashboard/` and is
mounted by Hermes at `/api/plugins/petasos/`. The plugin directory adds
`dashboard/manifest.json`, `dashboard/plugin_api.py` (one import of
`build_router`), and `dashboard/index.js`. The script is a placeholder that
shows the status response with Hermes's plugin SDK. The real front end
replaces that file. The manifest is generated by
`petasos.hermes.dashboard.manifest.render_dashboard_manifest`; a test fails
when the committed file drifts.

The route functions are thin. Each response is built by a plain function
that takes a home, a settings mapping, or a spool path and returns a dict.
Those functions do not import a web framework. Every body, including an
error, carries `version`. `GET /status` is version `2` because it now
includes the doctor report. Every other body, including an error, is
version `1`. A client ignores keys it does not know. A failure is
`{version, error: {code, message, path}}`. `path` is a settings path or
null. The message is one sentence. The server log holds the detail. There
is no stack trace and no long-lived stream: the front end polls.

Hermes's dashboard session protects these routes the same way it protects
the rest of `/api/`. `/api/plugins/` is not on the public allowlist in
`hermes_cli/dashboard_auth/public_paths.py`. `auth_middleware` in
`hermes_cli/web_server.py` answers a call with no session token with HTTP
401 `{"detail": "Unauthorized"}`. The plugin gate runs after that check, so
an unauthenticated caller learns nothing about whether the plugin is
mounted. A sandbox dashboard on `127.0.0.1` returned that 401; the same
call with `X-Hermes-Session-Token` returned the status body. The
placeholder calls `SDK.fetchJSON`, which sends that session. Petasos does
not add a second token. The active home is
Hermes's own resolution for the call (context-local override, then
`HERMES_HOME`, then the active-profile pointer). The client cannot pass a
path. A process that serves more than one profile follows whichever home
is active on that call, for reads and for writes.

`session_secret` and `hash_key` are never returned. Each is `set` or
`unset`. Text a person sees (a block message, a normalised input, an event
field that is not an id) goes through Hermes's redactor when that redactor
is available, and is withheld when it is not.

#### `GET /status`

```json
{
  "version": 2,
  "protection": "on",
  "switches": {
    "hermes": {"on": true, "detail": "Hermes is loading Petasos."},
    "petasos": {"on": true, "detail": "Petasos enforcement is on."}
  },
  "settings": {"valid": true, "error": null},
  "scanners": [
    {"id": "syntactic", "label": "Basic checks", "state": "active", "reason": null, "fix": null, "extra": null}
  ],
  "recommendations": [],
  "role": "general",
  "level": "balanced",
  "secrets": {"session_secret": "unset", "hash_key": "unset"},
  "home": "~/hermes",
  "petasos_version": "0.4.0",
  "doctor": {
    "verdict": "protected",
    "exit_code": 0,
    "summary": "Protected. Petasos is checking tool calls for this agent.",
    "home": "/home/me/.hermes",
    "home_reason": "the home Hermes is using",
    "checks": [
      {"id": "petasos", "status": "ok", "summary": "Petasos 0.4.0, running under Python 3.11.15.", "meaning": "", "next_step": ""}
    ],
    "suggestions": [],
    "protected_paths": [],
    "paths_summary": "Petasos watches 9 places an agent could change to turn protection off.",
    "detail": {}
  }
}
```

`protection` is `on` only when Hermes is loading the plugin, Petasos's
`enabled` is true, and the settings resolve. `switches.hermes.on` is true,
false, or null when the file cannot be read. `switches.petasos` is the arm
switch. `scanners` is the syntactic scanner plus one row per registry
entry: `state` is `active`, `unavailable`, `not_installed`, or `off`;
`reason` and `fix` are sentences. A pip install line is not used here.
When a package is missing, `fix` says to add `petasos[<extra>]` to the
plugin's dependency list and install the plugin again with Hermes.
`recommendations` is that same list of sentences the doctor prints under
Suggestions. `doctor` is the object `petasos doctor --json` prints, built
by the same check. `scanners` and `recommendations` are the rows and
sentences inside that object, not a second composition.

The dashboard does not start the plugin to re-validate it. Hermes's
validator imports the plugin in a subprocess, which is too much work for a
polled status. The `plugin_load` check then says the plugin was not started
again, and the file checks still run. `petasos doctor` does run the
validator. The approval line reads this process, the same way the command
does, so a dashboard process does not invent the gateway's unattended flags.

Each scanner row also carries `operating`, `{code, label}`: whether the
check is checking the agent's actions now (`running`, `paused`, `stopped`
while Hermes is not running Petasos or the settings cannot be used,
`failed`, `not_installed`, `off`). It is the one value every view draws a
check's state from, so a paused status never shows a check running; a
test fails if it does. `paused` is true when Hermes runs Petasos and its
own switch is off. `scope` says what "on" covers (every agent Hermes
starts from the profile, except in safe mode; a saved change applies from
the next action), and `checks_note` describes the checks without claiming
they run. `choices_note` is one sentence beside the job and strictness
when those choices are not in effect, and null when they are: while
protection is paused it says they apply when protection resumes; while
Hermes is not running Petasos it says they apply when Hermes runs
Petasos; while the settings cannot be used it says they are not in use
until the settings can be used. Job and strictness descriptions say what
the choice sets, not that protection is doing it now.

`coverage` is read from the same scanner rows: `running` and `missing`
(each `id`, `label`, `name`, the registry's purpose name with the product
after it, `state`, `operating`, and `covers`, what the check looks for in
plain words from the registry's capabilities; a missing one also
`recommended`, `reason`, `held`, true when a check that is turned on
cannot run, `consequence`, `{holds, title, sentence}`, what that does to
tool calls computed by the doctor from `fail_mode` and
`tools.dangerous_posture`, and `command`, the one command that adds
it, or null), `add_where` (where to run that command), and `complete`, true
only when every check runs. The tab says what is on and what is not from
it, so "on" never reads as complete coverage, and names a missing check by
what it adds before the product. `who_can_change` holds three sentences (`agent`, `you`,
`switches`); the agent's says that an attempt is recorded and is not
stopped by being recorded. `record_signing` is `signed`, the profile's
`env_file`, and, when unsigned, the `steps` to start signing.

`doctor.verdict` also requires the plugin files. `protection` does not: it
is only the two switches and whether the settings resolve. A profile whose
switches are on before the files are installed can report `protection: on`
while `doctor.verdict` is `not_protected`.

#### `GET /settings`

The four stored values, `labels` and `help` for those four, `roles`
(`name`, `label`, `description`, `suggests`) and `levels` (`name`, `label`,
`description`) in offer order, `sections` in declaration order (`path`,
`label`, `help`, `audience`, `restart`), and `settings`, one leaf per row,
in declaration order:

`path`, `section` (the parent path, or `""`), `value`, `default`, `type`,
`choices`, `choice_labels` (plain words per choice, or null), `bounds`
(`ge`, `gt`, `le`, `lt`), `label`, `help`, `audience`, `restart`, `origin`
(`default`, `role`, `level`, or `override`), `nullable`, and, on a row
whose origin is `override`, `reset_to` (`value`, `origin`): what removing
that override would leave. Every label and help sentence is declared with
`setting()` in `petasos/config/sections/` and the roles and levels in
`layers.py`; the front end derives none.

`locked` is read-only and comes from Hermes's managed config
(`hermes_cli.managed_scope.managed_config_keys`): `known` (false when this
Hermes cannot say), `stored` (pinned keys among the four), `settings`
(pinned leaf paths under `overrides`), and `plugin` (Hermes's plugin list
is pinned).

`secrets` is the set/unset pair. `valid` is false when the stored document
does not resolve; `problems` is `[{path, message}]` and leaf `value` /
`origin` are then null. The schema rows are still present.

#### `POST /settings/preview`

Body: any subset of `enabled`, `role`, `level`, `overrides`. `overrides` is
a patch: omitted keys stay. Response: `stored` (the merged four), `sections`,
`settings` (what the merge would resolve to), `changes` (leaves whose value
or origin would differ: `path`, `before`, `after`, `origin_before`,
`origin_after`, `restart`, `applies`), `applies` (one sentence for the
whole preview), `valid`, `problems`. Nothing is written. An
invalid candidate is `valid: false`, `changes: []` and `applies` empty,
with HTTP 200. `applies` on a restart-bound change says an agent started
from now on uses the saved value, and an agent already running keeps the
previous value until it restarts. The response does not say whether any
running agent has restarted. A live change applies from the next tool call.

#### `PUT /settings`

The same body as preview. Invalid settings are HTTP 400
`invalid_settings` with `path` and the schema's sentence, and nothing is
written. A secret key is HTTP 400 `secret`: those values are not set here.
Hermes refusing a managed install or a pinned key is HTTP 403 `managed`,
with a sentence that tells the person to change the managed configuration.
If Hermes's writer is absent, HTTP 503 `writer_unavailable`.

Success is the `GET /settings` body plus `saved: true`, `restart` (leaf
paths whose value changed and whose spec needs a restart), and
`restart_message`. For a restart-bound change that sentence says an agent
started from now on uses the saved value, and an agent already running
keeps the previous value until it restarts. It does not claim to know
whether a running agent has restarted. A live change says Petasos uses it
from the agent's next tool call. When one save changes both, the sentence
says so.

Clearing is not a patch. Hermes's writer deep-merges a mapping and keeps
keys the new document omits, and `None` does not replace a mapping. A list
does replace a mapping. `DELETE /overrides` removes every override.
`DELETE /overrides/{path}` removes one dotted path (`scanners.presidio.score_threshold`).
The save writes a list and then the mapping that should remain, so the
removed key is gone. Between those two writes a reader can see a list; the
enforcer keeps the last settings that resolved. The response is
`cleared`, `message`, `restart`, `restart_message`, and `settings` (the
`GET /settings` body without its own `version`). A path that is not set
returns `cleared: false` and does not write.

#### `POST /playground`

Body: `text` and optional `direction` (`inbound` or `outbound`), or `tool`
and `arguments`, plus optional `settings` (the same patch as preview). Not
both text and a tool. Over 20,000 characters is HTTP 400 `too_large`.

```json
{
  "version": 1,
  "decision": "block",
  "message": "[BLOCKED by Petasos] ...",
  "findings": [
    {
      "rule": "petasos.syntactic.injection.ignore-previous",
      "severity": "high",
      "confidence": 1.0,
      "span": {"start": 0, "end": 28},
      "sentence": "Looks for text that tells the agent to ignore earlier instructions."
    }
  ],
  "findings_omitted": 0,
  "normalized": null,
  "normalized_changed": false,
  "scanners": [
    {"id": "syntactic", "label": "Basic checks", "participated": true, "state": "active", "reason": null}
  ],
  "timed_out": false
}
```

`decision` is `allow`, `block`, `approve`, or `flag`. Text coming in is a
tool result, which Petasos never withholds: it is `flag` when a finding
that is not personal information would block, the same test the result
hook uses, and `message` is the warning the agent would see above it.
Text going out is what the agent writes into a tool call, and a call
carrying it is `block`. The tool is not known for text, so messages name
it `<tool>`. `outcome` is the decision in words (`code`, `label`,
`sentence`), and `confidence_help` says what a finding's `confidence`
measures. `message` is what the model would see, after redaction, or
empty on allow. `span` is null when the
finding has no position. `normalized` is the normalised input when it
differs, otherwise null. `scanners` lists the syntactic scanner and each
registry entry that was considered. `participated` is false for `off`,
`not_installed`, `unavailable`, and for a check that did not finish.
`link`, when set, is `{href}`: `#overview?panel=checks` for a check that
is not installed, and `#settings?path=scanners.<id>.enabled` for one that
is turned off. `check_note` says the check runs no command, writes no
file, sends nothing, and adds no Activity record.
PromptGuard does not take part, and no download starts, when its weights
are not on disk; `reason` says so. Semgrep without a lifecycle owner is
unavailable for the same reason the gateway's composition reports.
Composition and the scan each stop after 2 seconds. `timed_out` is then
true and `decision` is `allow` with a sentence that the preview has no
decision.

The call builds a new pipeline and a new guard from the resolved settings.
It uses an empty secret, a private session id, a discarding event sink, and
an explicit protected-path list for that home. It does not open the
enforcement spool and it does not read or write another session's state.

`anonymized` is the pipeline's sanitized text, display-redacted and clipped by
`_show`, or null. `anonymization` is `{code, sentence}`: it names disabled
anonymization, a missing, disabled, failed or unfinished personal-information
check, no personal information, excluded entity kinds, or successful hiding.
Tool trials retain the result of the guard's existing scan; no second scan runs.

`risk` is `{score, tier, thresholds, sentence, threshold_sentence, note}`.
`score` and the plain-language `tier` describe this input alone, or are null
when the check times out, scoring is disabled, or guard-only settings prevent
risk calculation (the text result is still returned). Each threshold is
`{label, score}`. Text trials score their findings on a separate fresh tracker
with the guard's per-scan cap, leaving the text decision unchanged. Tool trials
read their own throwaway guard's tracker after evaluation. The note explains
that real conversations include earlier inputs and decay; no live conversation
is read or changed. Protection-stage reporting being off does not disable the
guard's risk thresholds.

#### `GET /playground/examples`

`examples` (each `id`, `label` saying what it demonstrates, a one-line
`description`, `kind` (`text` or `tool`), and its input: `text` with
`direction`, or `tool` with `arguments`), `default`, the one Try it
opens with, and `check_note`, the sentence beside Check. They are
served from the wheel, not written in the tab's script: Hermes scans a
plugin directory for dangerous strings before it loads the plugin
(`tools/plugin_guard.py`), and a sample attack in the script gave the
directory a `dangerous` verdict, so Hermes refused to load Petasos. A test
keeps such strings out of the plugin directory, and the tab's sources
live in `hermes-plugin/dashboard-src/`, outside the installed directory.

#### `GET /activity`

Query: `cursor`, `limit` (1 to 100, default 50), `since`, `until` (unix
seconds), `kind` (event type), `tool`, `session`, `severity`, `outcome`
(comma-separated outcome codes, at most 20), and `q`: the start of an event
id, or words matched against the event's sentence, tool, conversation,
rule, kind and reason.

```json
{
  "version": 1,
  "events": [
    {
      "scan_id": "e-...",
      "timestamp": 0,
      "event_type": "quarantine",
      "tool": "terminal",
      "summary": "Blocked a shell command that would delete files recursively.",
      "integrity": {"status": "verified"}
    }
  ],
  "next_cursor": null,
  "cursor_reset": false,
  "complete": true,
  "skipped_lines": 0,
  "integrity": {"mode": "off", "reason": "No session secret is set, so events are not signed and cannot be checked.", "checked": 0, "failed": 0}
}
```

Events are newest first. Each event is the stored record (content fields
redacted; ids are not) plus `summary`, `outcome`, `matched_note` (the
matched text is not kept, and why) and `integrity`, which carries
`meaning`: what the signature proves and what it cannot. `severity_label`
is the word for the severity column: a stored rank in plain words, `Conversation risk`
for a block from the conversation's risk score, `No rule` when no rule
matched, and `Not recorded` when a rule is named and the event stored no
rank. There is no dash. An attempt to
change the guardrails (`selfmod_attempt`) takes its outcome from the event
the enforcer wrote next for the same call (same conversation and tool,
within seconds): `attempt_blocked`, `attempt_asked`, or `not_stopped`,
with `outcome_note` and the `target`. Recording an attempt does not stop
the call. `risk_block` is true when the call was stopped by the
conversation's risk score (a `block` or `tier3` event, or an attempt the
enforcer then blocked that way), so the tab can lead to the earlier
warnings that built it. `integrity.status`
is `verified`, `failed` (with `reason`), or `off`. The page `integrity.mode`
is `verified`, `mixed`, `failed`, or `off`. `label` is the badge: when
`verified`, `{n} signatures verified`. `limit` and `limit_label`, only when
every signature on the page matched, are the disclosure: a matching
signature shows the entry was not altered, and cannot show that no entry
was deleted. `off` means no usable session
secret; the reason says which. Failed events are still returned.

`next_cursor` is opaque. Send it back as `cursor` for the next, older page.
A cursor that points past a file that has shrunk sets `cursor_reset` and
returns the newest page. A line that is not JSON is counted in
`skipped_lines` and skipped. A trailing partial line is left unread. The
rotated sibling `<spool>.rot` is older than the live file and is read after
it. One request reads at most 1 MiB, from the end or from the cursor, and
sets `complete` false when older bytes remain.

#### `GET /activity/summary`

The same time, kind, tool, session, severity, outcome and text filters.
`total` is the number of matching events, the rows the list shows.
`blocked` is the number of tool calls among them that did not run: events
whose outcome is `blocked`, `stopped` or `attempt_blocked`, with an attempt
and the block written for the same call counted once when both match.
Also `by_kind`, `by_severity`, `by_tool`, `by_session`, `by_outcome`,
`figures`, `finding`, `kind_labels`, `complete`, `integrity`. `figures` is
one `{code, label, count, outcomes}` per outcome that occurred. Codes that
share a label are one figure. The counts add up to `total`.
`not_stopped` is not a figure: those events are counted in `Other`, and
`finding` is `{count, sentence, action}` when that count is above zero,
otherwise null. The sentence says the record cannot show whether a change
took effect. `action` is `Review current settings`. The read cap is 4 MiB
of the newest bytes.

#### `GET /activity/{scan_id}`

`{version, event, complete, integrity}` for one event, or HTTP 404
`not_found`.

#### What the install command copies

`petasos hermes install` copies `hermes-plugin/petasos/dashboard/`
(`manifest.json`, `plugin_api.py`, `index.js`) into the profile plugin
directory beside `plugin.yaml`, or regenerates `manifest.json` from
`render_dashboard_manifest()`. The wheel supplies the router. The front end
replaces `index.js` and does not need another server, token, or copy of
the schema.

## 9. Public API

`petasos.__all__` is exactly:

```
Pipeline  PipelineResult  PetasosConfig  Settings  resolve  ConfigError  Secrets
Scanner  ScanResult  ScanFinding  Severity  Direction  Position  MinimalScanner
Enforcer  Decision  Allow  Block  Approve  ToolCall
__version__
```

A test pins the list. Everything else is importable from its submodule and
carries no stability promise.

## 10. Style

Code

- Frozen dataclasses for data. Plain functions for policy. A class only where
  there is state to own.
- No module-level mutable state.
- A module over 500 lines is a prompt to split; over 800 needs a stated reason.
- One name per concept across Python, JavaScript, docs and logs.
- `from __future__ import annotations` everywhere; `mypy --strict` with no new
  ignores; ruff as configured.

Comments

- A comment states a constraint the code cannot show. It describes the code as
  it is.
- No ticket ids, no history, no "previously". That belongs in the commit
  message and `CHANGELOG.md`.
- Every public name has a docstring whose first line says what it guarantees.
- Rationale longer than three lines goes in `docs/architecture/` and is
  referenced by section title.

Tests

- Tests call the public API and assert behaviour.
- No test asserts on source text, line numbers, call-site counts or doc
  wording. Structural rules live in `tests/test_architecture.py`.
- Files mirror the package: `tests/<package>/test_<module>.py`. No file is
  named for a ticket.
- Scanner wrappers are tested against real backends, never mocks.
- Reference docs are generated from `describe()`; CI regenerates and fails on
  a diff. Marker-comment doc assertions are removed.

## 11. Removals

| What | Why |
|---|---|
| `scanners/llm_guard.py`, `scanners/llama_firewall.py`, their extras, CI lanes, tests, docs, and their rule ids in role data | Deprecated in 0.5; the removal window opens with the next release |
| `session/license.py`, `session/_keys/`, `Pipeline.activate`, every `PETASOS_LICENSE_KEY` read, the `pyjwt` dependency | Gates nothing; breaks the zero-dependency base install |
| `console/_config_meta.py`, `console/_presets.py`, the JS preset comparator | Replaced by `describe()` and `layers.py` |
| `session/profiles/` | Replaced by `layers.py` |
| `docs/deployment/reference_plugin/` | Replaced by `petasos.enforce` and `petasos.hermes` |
| `profile_lint.py` | No package consumer |
| `scripts/pet135_replay.py`, `pet242_copy_footprint.py`, `pet184_dispatch/`, `pet200_calibrate.py` and its test | One-off ticket artefacts |
| Tracked files under `docs/specs/` | The directory is gitignored; the files predate that |
| `assets/petasos-shield.svg` | Unreferenced |
| The default `host_id` and the "enterprise" wording | Leftovers |

## 12. Work packages

Each package runs in its own worktree off `arch/redesign` and merges back in
the order shown. Every package must leave ruff, `mypy --strict` and the full
test suite green.

**Wave 0. Baseline (one lane, before anything merges)**

- Build a Python 3.11+ environment (`uv` and Python 3.11/3.12 are on this
  machine; the system `python3` is 3.9 and cannot run the suite) with the dev,
  console, presidio and prompt-guard extras. Record test counts, coverage on the five core modules,
  and benchmark means.
- Record a verdict baseline: for every input in `tests/adversarial/` and the
  composition corpus, under each built-in profile, the fields `safe`, blocking
  rule ids, and tier. Commit it as a fixture. This is the parity oracle for
  Waves B and C.

**Wave A. Subtraction (parallel)**

| Package | Scope | Owns |
|---|---|---|
| A1 | Remove LLM Guard and LlamaFirewall | their modules, tests, lanes, extras, doc mentions, `bootstrap.py` rows |
| A2 | Remove license machinery and `pyjwt` | `session/license.py`, `_keys/`, license code in `pipeline/pipeline.py`, plugin, `_standalone.py` |
| A3 | Repository hygiene | `scripts/`, `docs/specs/`, `assets/`, stale lines in `CLAUDE.md` and docs |

A4, after A1 and A2 merge: one severity rank beside `Severity`, the dead
`load_health` path in the pipeline (no scanner implements it once LLM Guard is
gone), and the one outstanding lint error. Shared defaults are not
de-duplicated here: B4 and C1 rewrite every site that holds one.

**Wave B. Config core**

| Package | Scope | Depends on |
|---|---|---|
| B1 | `config/schema.py` with exhaustive tests | Wave A |
| B2 | `config/sections.py`, `layers.py`, `migrate.py` | B1 |
| B3 | `scanners/registry.py`, reading the scanner sections B2 defines | B2 |
| B4a | Internals read the new tree; a temporary bridge keeps old callers working | B2 |
| B4c | Delete the old config, the bridge, profiles, presets and the old bootstrap | **Done** |

The cutover is staged so that the existing test suite checks it.

**B4a** moves every component (pipeline, guard, frequency, escalation, audit,
alerting, lineage, taint) onto the new tree. One temporary module,
`petasos/config/legacy.py`, converts an old flat config and an old profile
into the new tree at the public constructors, reproducing the old leniencies
for old inputs. With it, the 3,400 existing tests run unchanged against the
new internals, which is the proof that the internals are right. Nothing but
that module may import the old config or the profiles package.

The one deliberate behaviour change lands here: the guard no longer takes
tier thresholds from a profile. The parity record holds two arrangements per
old profile, the profile passed to both pipeline and guard and the profile
passed to the pipeline only (`plugin:<profile>`, what the Hermes plugin
does). They differ only for `admin` and `research`. After B4a every
`plugin:` arrangement, and every arrangement of the other profiles, must
replay with no change to the record; the `admin` and `research`
guard-with-profile entries become equal to their `plugin:` twins and are
re-recorded in the same commit.

**B4c is done.** The flat config, the bridge, `session/profiles/`, and the old
bootstrap are gone. `PetasosConfig` is the tree. The parity adapter builds each
old profile label through `migrate` and `resolve`. `petasos config migrate` is
the remaining reader of the old field names.

**Wave C. Structure (C1 and C3 after B4a, alongside T; C2 after C1; C4 after B4c)**

| Package | Scope |
|---|---|
| C1a | `enforce/` as functions: lift the plugin's decisions, fallback, approvals, messages and event spool into the library unchanged; the plugin calls them |
| E0 | Enforcement parity oracle: host-neutral scenarios and the reference plugin's recorded outcomes for them, in `tests/enforce_parity/` |
| C1b | `Enforcer`: the stateful object of section 6, written beside the plugin and accepted when it replays the E0 record. The plugin is not rewired; it is retired in C2 |
| C2 | `hermes/` and `cli.py`: adapter, manifest, doctor, install, tested against upstream Hermes in a throwaway home. **Removal done:** `docs/deployment/reference_plugin/` is gone and the enforcement record in `tests/enforce_parity/` is frozen. Needs C1b |
| C3 | The Petasos tab's API: served by Hermes's dashboard, built on `describe()`, `resolve()`, the registry and the event spool, writing through Hermes's settings writer. **Removal done:** `petasos/console/`, the `petasos-console` script, and the `console` extra are gone |
| U | The Petasos tab's front end, on Hermes's plugin kit, built in the judged loop of section 8.4; the plain-language pass over every description |
| S1 | Guardrail integrity (`guardrail-integrity.md`) |
| S2 | Deferring to Hermes where it already decides (section 8.5) |
| C4 | **Done.** Module splits and renames: `guard/`, `pipeline/`, `scanners/minimal/`, `scanners/semgrep/`, `model.py`; public API pinned to section 9 |

**Wave D. Finish**

| Package | Scope |
|---|---|
| D1 | Test suite restructured to section 10; `tests/test_architecture.py` |
| D2 | Docs generated from the schema; `CLAUDE.md`, `README.md` and usage docs rewritten; wiki decision record |
| D3 | Comment sweep to section 10 |
| D4 | Researcher soak: install from the branch on the migrated researcher Hermes, `role: research`, run through the daily crons |

## 13. Recorded decisions this supersedes

One new wiki decision will supersede these, each with a back-link:

- 2026-06-14, strength-preset registry kept separate from `profile_name`.
- 2026-06-17, the reference plugin as a hand-synced deployment artefact.
- 2026-06-23, retire inert settings from the editor but keep the field.
- 2026-09-06, the config builder stays in the plugin because of version skew.

These stand: one atomic `reconfigure`; scanners built in one place; per-Hermes-
profile scope for every field; classic scripts with no bundler. The operator
tool they describe is now the Petasos tab, which Hermes's dashboard serves and
authenticates; the standalone console and its optional auth are retired
(`console-retirement.md`).

## 14. Open questions

1. Everything listed in section 7.6.
2. Whether `scanners.presidio.score_threshold` and the entity lists can become
   live-appliable cheaply, or stay `restart`.
3. Whether the console keeps a settings editor once the host renders one, or
   becomes activity and diagnostics only. Decide after the researcher soak.
   Answered below, 2026-11-17.

### Settled after the soak, 2026-11-17

- **The tab keeps its settings editor.** Hermes already renders a form for
  Petasos, but only in Desktop: it draws `config_schema` from `plugin.yaml`
  as a flat form, with `overrides` as a raw JSON field. The web dashboard
  renders no `config_schema` at all ([native fit](hermes-native-fit.md),
  section 4). A dashboard user would have no other place to change a
  setting, and nobody can read the override tree from a JSON field. Both
  forms write through Hermes's one settings writer, so they cannot drift.
  Revisit if the dashboard gains a `config_schema` renderer: the tab's
  Settings page would then keep only what a flat form cannot show.

### Settled by the owner, 2026-11-11

- **Credits and the donation panel** from the old About page go in the
  README, as a footer. The tab does not carry them. The owner proofreads the
  README before it is called done.
- **A list in a layer or an override replaces the list beneath it.** No
  additive form for now.
- **Semgrep cannot be turned on inside Hermes.** Nothing in the adapter owns
  the engine's lifecycle, so `on` can only fail. Building it showed `auto`
  fails the same way: it asks for a check that cannot start, and that blocks
  tool calls that change things. So the settings form offers only Never,
  every save that would leave Semgrep on is refused, and `doctor` says so
  plainly and names the command that turns it off. A hand-written `on` or
  `auto` still fails closed. One place answers whether Hermes can run
  Semgrep (`petasos/hermes/semgrep_host.py`). Running it inside Hermes is
  wanted later and is its own package.
- **No compatibility path for the 0.18 fork**, as section 7 says. Petasos
  support there is not a goal.
- **Two switches stay.** Hermes's plugin list decides whether Petasos loads,
  and Petasos's `enabled` pauses it. The tab offers only Pause. `doctor` and
  the tab say which of the two is off.

- **Pinning covers the plugin list as well as Petasos's settings.** Hermes
  pins a list as one value, so pinning Petasos as enabled fixes which plugins
  load: none can be turned on or off until the profile is unpinned. Pinning
  only the settings would leave `hermes plugins disable petasos` working,
  which is the case pinning exists for. `petasos hermes pin` says what it
  fixes before anything is written. Design in
  `docs/architecture/guardrail-integrity.md`.

Left for a later polish pass: the light theme's single blue, and which
product the owner meant as the visual reference.
