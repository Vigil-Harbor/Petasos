# Petasos redesign: contracts

Status: draft for build. Branch `arch/redesign`. Targets the release after 0.5.0.

This document fixes the interfaces the redesign is built against. Work packages
in section 12 are briefed from it. Where it contradicts `CLAUDE.md` or older
docs, this document wins until those are rewritten (package D2).

Section 7 (Hermes binding) is written against
`plugin-surface.md` (kept outside this repository), a source-level
report on upstream Hermes at `v0.23.1`. That report read code and ran nothing,
so section 7's host facts are confirmed on the migrated researcher in package
C2 before anything depends on them.

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
  model.py           Scanner protocol, findings, results, Severity and its rank
  normalize.py
  config/
    schema.py        setting(), describe(), from_mapping(), to_mapping(), ConfigError
    sections.py      section dataclasses and the PetasosConfig root
    layers.py        roles, levels, resolve(), Resolved
    migrate.py       0.5 flat section -> settings (one-shot)
  scanners/
    registry.py      ScannerSpec, REGISTRY, compose()
    minimal/         rule families, one module each
    prompt_guard.py  presidio.py
    semgrep/         adapter, engine, process, runtime, source, roots
  session/           frequency, escalation, audit, alerting, lineage, taint
  pipeline/
    pipeline.py      orchestration only
    findings.py      merge, suppression, floors, safe computation
    health.py        timeouts, circuit breaker, scanner health
  guard/
    guard.py         the evaluate ladder
    tools.py         tool classification table (data)
    params.py  selfmod.py  fanout.py
  enforce/
    enforcer.py      lifecycle state machine and the host-facing API
    decisions.py     dangerous-tool ladder, egress fence, taint
    fallback.py      syntactic-only gate for cold start and init failure
    approvals.py     approval observation, excerpt redaction
    events.py        signed event spool
    messages.py      model-facing block and notice text
  hermes/
    plugin.py        register(ctx): hook wiring and translation only
    home.py          Hermes home and profile path resolution
    settings.py      read and watch the settings block
    manifest.py      generate plugin.yaml from the schema
    doctor.py
  console/           optional extra: app.py, routes/, static/
  cli.py             the `petasos` command
```

Imports point one way:

```
model, normalize < config < scanners, session < pipeline < guard < enforce < hermes < console < cli
```

Only `hermes/` knows Hermes exists. Nothing imports `console/`. One test
(`tests/test_architecture.py`) enforces the direction by parsing imports.

No module name starts with an underscore. A package's public names are what its
`__init__.py` lists in `__all__`.

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
- A `rules` entry that reaches a floor is an error. (Today it is stripped
  with a warning.) `rules.suppress` may not name a structural or
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
`tools.aliases`, `scanners.presidio.entities_extra`.

A level may set only: `fail_mode`, `escalation.tier1..3`,
`scanners.presidio.score_threshold`, `anonymization.enabled`.

A test asserts the two sets are disjoint and that every built-in stays inside
its set. Merge order between role and level therefore never matters.

### 4.2 Built-ins

Roles, replacing the five profiles:

| Role | Was | Sets | Suggests |
|---|---|---|---|
| `general` | general | nothing | balanced |
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
profile, or an explicit null, is `general`, which has the same rule levers as
no profile. An unknown profile is dropped, and the note names the roles.
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

`petasos.enforce.Enforcer` is the host-facing object. It owns everything the
reference plugin does today except Hermes-specific wiring.

```python
class Enforcer:
    def __init__(self, source: SettingsSource, *, secrets: Secrets, host: HostInfo,
                 events: EventSink | None = None) -> None
    def start(self) -> None                         # begins background init, returns at once
    def tool_call(self, call: ToolCall) -> Decision
    def tool_result(self, call: ToolCall, result: str) -> str | None
    def session_started(self, session_id: str) -> None
    def subagent_started(self, child: str, parent: str) -> None
    def subagent_stopped(self, child: str) -> None
    def approval_requested(self, request: ApprovalRequest) -> None
    def approval_answered(self, answer: ApprovalAnswer) -> None
    def status(self) -> Status
    def close(self) -> None

Decision = Allow | Block | Approve       # frozen dataclasses; Block and Approve carry model-facing text
```

- The API is synchronous. The enforcer owns its event loop thread.
- `SettingsSource` is a callable returning the current settings mapping and a
  change token. The enforcer polls it and reconfigures; the host decides where
  settings live.
- `HostInfo` states what the host can do: whether an approve directive exists,
  whether sub-agent hooks fire, callables for "auto-approve is on" and "this
  rule is always approved", and a stable host id. The library never imports a
  host.
- State is on the instance. There are no module-level globals and no
  `_reset_*` test hooks; a test builds a fresh `Enforcer`.
- The lifecycle is an explicit state: `disarmed`, `starting`, `ready`,
  `failed`. `starting` and `failed` route through `fallback`, which scans with
  the syntactic scanner only and applies `fail_mode`.
- `tool_call` never raises. An internal error becomes a `Block` or `Allow`
  according to `fail_mode`, plus an event.

The decision ladder, egress fence, taint store, approve posture, approval
observation and block-message formatting move here from the plugin with their
behaviour unchanged. The guard reads tier thresholds, exemptions and aliases
from the resolved config, so there is no separate profile argument to forget.

Events are written through `EventSink`. The default sink is the signed spool
that the console reads; it moves from `console/` to `enforce/events.py`.

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
drift in any way that changes enforcement. It exists because Hermes renders a
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
`type: secret`, so Hermes stores them in the profile's `.env` as
`PETASOS_SESSION_SECRET` and `PETASOS_HASH_KEY`.

Rules the host imposes:

- Defaults live in Petasos. The schema's `default` is display only.
- Settings are read with `ctx.get_config` on each call, never captured in
  `register()`. Hermes sends no change notification. `hermes.settings` wraps
  this as the enforcer's `SettingsSource` and derives the change token from
  the four values.
- Nothing but Hermes writes `config.yaml`. The plugin uses `ctx.set_config`;
  the console and the CLI use Hermes's own writer. A plain YAML dump by another
  process has already misplaced keys once on this machine.
- Hermes expands `${NAME}` inside setting values. Petasos settings never need
  that sequence; `doctor` flags one if it appears.

### 7.3 Hooks

`petasos.hermes.plugin.register(ctx)` builds one `Enforcer`, registers the
hooks below, and translates between hook arguments and `ToolCall` /
`Decision`. It contains no policy.

| Hook | Use | If the callback fails |
|---|---|---|
| `pre_tool_call` | The enforcement point: block, or hand to Hermes approval | Hermes blocks the call on an exception or after its 30 s hook timeout |
| `transform_tool_result` | Annotate ingested content | Hermes passes the result through unchanged |
| `post_tool_call` | Taint and audit bookkeeping | Ignored |
| `on_session_start` | Session bookkeeping | Ignored |
| `subagent_start`, `subagent_stop` | Lineage | Ignored; the fan-out budget is enforced on the `delegate_task` tool call |
| `pre_approval_request`, `post_approval_response` | Approval observation | Ignored |

Consequences for the enforcer:

- Its own time limits sit below the host's 30 s, so a slow scan becomes a
  Petasos decision under `fail_mode` and not a host timeout.
- `tool_result` catches everything and always returns a string, because the
  host fails open there.
- Hermes grants `approve` automatically in profiles whose approval mode is
  set to approve, which includes the researcher. There `dangerous_posture:
  approve` means allow. `HostInfo` reports it and `doctor` warns.
- Some tool calls arrive with only a `task_id`. Session-keyed state keeps
  today's fallback.
- A plugin that failed to load enforces nothing, silently. `doctor` checks
  that the plugin is enabled and loaded, so a watchdog can call it.

Hermes offers two further fail-closed levers that Petasos does not use today:
`pre_llm_call` can block a turn, and `transform_llm_output` with
`hold_stream=True` can withhold a reply. Using them adds enforcement surface.
That is new function, not restructuring, and is left for after the redesign.

### 7.4 Self-protection

Nothing in Hermes stops the model from running `hermes plugins disable
petasos`, editing the plugin directory, or changing
`plugins.entries.petasos`. The guard's self-modification rules are the only
lever. C2 checks what they cover today and extends them to those three.

### 7.5 Commands

- `petasos doctor`: install state, plugin enabled and loaded, manifest in
  step with the wheel, scanner states, resolved settings with origins,
  recommendations. Replaces `verify.py`.
- `petasos hermes install`: puts the plugin directory in place for a profile
  and enables it.
- `petasos config migrate`: section 4.3.

### 7.6 Open until C2 runs on the researcher

- The install route. Either `hermes plugins install` from a git reference
  that resolves to the plugin directory, with Hermes installing the wheel
  named in its `pyproject.toml`; or `petasos hermes install` writing the
  directory out of the wheel's package data. Upstream advises against adding
  packages to a managed Hermes environment with raw pip, and whether its
  package manager admits the wheel from where Petasos publishes is untested.
- Whether settings written through the Desktop form reach a running gateway
  without a restart.
- Hook delivery in a managed kanban worker, where the settings a plugin reads
  are those frozen at session creation.

## 8. Console

The console is a view. It reads `describe()` for the editor, `resolve()` for
effective values and origins, the registry for scanner states, and the event
spool for activity. It writes settings through the same writer the host uses.

- It holds no field metadata, validation, role or level data of its own. The
  JavaScript receives all of that from the API and mirrors nothing.
- `server.py` splits into `app.py` plus one module per route group (config,
  events, history, approvals, health, playground).
- The ordered classic-script frontend and the no-bundler rule stand.
- The single `petasos` command gains `petasos console`; the separate
  `petasos-console` script is removed.

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
| `profile_lint.py`, `_limits.py` | No package consumer; three lines |
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
| A2 | Remove license machinery and `pyjwt` | `session/license.py`, `_keys/`, license code in `pipeline.py`, plugin, `_standalone.py` |
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
| B4c | Delete the old config, the bridge, profiles, presets and the old bootstrap | every caller migrated (C1, C3, T) |

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

Callers then move off the old config in parallel, each in its own package:
the plugin's logic in C1, the console in C3, and the core tests in **T**
(two or three lanes split by directory, a mechanical rewrite of how tests
build configs). **B4c** runs when nothing imports the bridge: it deletes the
old flat config, the bridge, `session/profiles/`, the presets, the old
bootstrap and the legacy parity tests, and points the parity adapter at the
new API.

**Wave C. Structure (C1 and C3 after B4a, alongside T; C2 after C1; C4 after B4c)**

| Package | Scope |
|---|---|
| C1a | `enforce/` as functions: lift the plugin's decisions, fallback, approvals, messages and event spool into the library unchanged; the plugin calls them |
| E0 | Enforcement parity oracle: host-neutral scenarios and the reference plugin's recorded outcomes for them, in `tests/enforce_parity/` |
| C1b | `Enforcer`: the stateful object of section 6, written beside the plugin and accepted when it replays the E0 record. The plugin is not rewired; it is retired in C2 |
| C2 | `hermes/` and `cli.py`: adapter, manifest, doctor, install, tested against upstream Hermes in a throwaway home; the reference plugin and its tests are retired into it. Needs C1b |
| C3 | Console rebased on `describe()` and `resolve()`; `server.py` split |
| C4 | Module splits and renames: `guard/`, `pipeline/`, `scanners/minimal/`, `scanners/semgrep/`, `model.py` |

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
profile scope for every field; the console as an operator tool with optional
auth; classic scripts with no bundler.

## 14. Open questions

1. Everything listed in section 7.6.
2. Whether `scanners.presidio.score_threshold` and the entity lists can become
   live-appliable cheaply, or stay `restart`.
3. Whether the console keeps a settings editor once the host renders one, or
   becomes activity and diagnostics only. Decide after the researcher soak.
