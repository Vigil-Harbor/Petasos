# Petasos redesign: contracts

Status: draft for build. Branch `arch/redesign`. Targets the release after 0.5.0.

This document fixes the interfaces the redesign is built against. Work packages
in section 12 are briefed from it. Where it contradicts `CLAUDE.md` or older
docs, this document wins until those are rewritten (package D2).

Section 7 (Hermes binding) is provisional. It will be finalised against
`plugin-surface.md` (kept outside this repository), which a separate
thread is producing from current upstream Hermes.

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

Config is a tree of frozen, slotted dataclasses. Every field is declared with
`setting()`:

```python
@dataclass(frozen=True, slots=True)
class EscalationConfig:
    enabled: bool = setting(True, help="Raise enforcement as a session keeps misbehaving.")
    tier1: float = setting(15.0, gt=0, help="Risk score at which tier 1 starts.")
    tier2: float = setting(30.0, gt=0, help="Risk score at which tier 2 starts.")
    tier3: float = setting(50.0, ge=TIER3_FLOOR, help="Risk score at which the session is terminated.")

    def check(self) -> None:
        if not self.tier1 < self.tier2 < self.tier3:
            raise ConfigError.at("escalation", "tiers must be strictly ascending")
```

`setting(default, *, help, ge, gt, le, lt, restart=False, audience="advanced", normalize=None)`
returns a `dataclasses.field` whose metadata carries a `FieldSpec`. No
third-party library is involved.

| Argument | Meaning |
|---|---|
| `help` | One plain-language sentence. Required. Shown in every UI and in the docs. |
| `ge` `gt` `le` `lt` | Numeric bounds. Numbers must be finite. |
| `restart` | True when a change needs a process restart to take effect. |
| `audience` | `basic`, `advanced` or `expert`. Controls which UIs show the field. |
| `normalize` | Optional per-item function for string tuples, such as `str.upper`. |

Rules the engine applies from the annotation alone:

- `bool` accepts only `bool`. `int` and `float` never accept `bool`.
- `Literal[...]` accepts only its members; the members are the choices.
- `tuple[str, ...]` rejects a bare string, accepts a list, strips each item,
  and rejects empty items.
- `Mapping[str, X]` is frozen on construction.
- `X | None` accepts `None`.
- A dataclass-typed field is a nested section.

A section may define `check(self)` for cross-field rules. Nothing else
validates config: no hand-written `__post_init__`, no parallel metadata table.

### 3.2 Engine API (`petasos.config.schema`)

```python
def from_mapping(cls: type[T], data: Mapping[str, Any]) -> T
def to_mapping(obj: Any) -> dict[str, Any]
def describe(cls: type) -> tuple[FieldInfo, ...]
def merge(base: Mapping[str, Any], layer: Mapping[str, Any]) -> dict[str, Any]

class ConfigError(ValueError):
    errors: tuple[tuple[str, str], ...]     # (dotted path, message)
```

- `from_mapping` is strict. An unknown key is an error naming the path and the
  nearest valid key. (Today unknown keys are silently dropped, so a typo is a
  no-op.) It collects every error before raising.
- `describe` returns one `FieldInfo` per leaf: dotted path, type name, default,
  choices, bounds, help, audience, restart flag. This is the only source for
  the console editor, the Hermes manifest and the generated docs.
- `merge` deep-merges partial documents. Mappings merge; everything else
  replaces.

### 3.3 The tree

`PetasosConfig` is the root. Scanner sections are declared next to their
scanner and collected under `scanners` by the registry (section 5).

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
- `detect_rtl_override` and `fold_leet` are deleted. The current code
  documents both as changing no pipeline outcome (the pipeline keeps only the
  normalized text; the syntactic scanner folds and detects on its own). B2
  confirms that with a test before deleting; `normalize()` keeps its own
  keyword arguments for direct callers.
- `Pipeline.inspect` loses its per-call `profile` argument. A pipeline is
  bound to one resolved config. If the console playground needs to preview a
  different role, it resolves a second config and builds a second pipeline
  over the same scanners.
- `disabled_scanners` and `semgrep_enabled` are replaced by per-scanner
  `enabled`.
- `profile_name` is replaced by `role` (section 4), which is not part of the
  tree.
- `rules.suppress` naming a structural rule, and `rules.severity_overrides`
  targeting one, are errors. (Today they are stripped with a warning.)

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

Everything under `scanners.<id>` is `restart` in the first cut. A change that
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
| `admin` | admin | full PII entity set | strict |

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
field; a test asserts it.

Roles and levels are frozen data in `layers.py`. Custom named profiles are
dropped: a role plus `overrides` covers the case, and nothing outside tests
registered one.

### 4.3 Migration

`petasos config migrate` reads a 0.5 flat `petasos:` section and prints the
equivalent `Settings`: `profile_name` becomes `role`, a preset match becomes
`level`, remaining differences become `overrides`, dropped fields are listed.
There is no runtime support for the old format.

## 5. Scanner registry

```python
@dataclass(frozen=True)
class ScannerSpec:
    id: str                          # equals Scanner.name and the key under `scanners`
    label: str
    extra: str | None                # pip extra that provides the backend
    detects: frozenset[Capability]   # "injection" | "pii" | "code"
    settings: type                   # the section dataclass
    default_enabled: Enabled         # "auto" for prompt_guard and presidio, "off" for semgrep
    build: Callable[[Any, BuildContext], Scanner]

REGISTRY: tuple[ScannerSpec, ...]

def compose(config: PetasosConfig, context: BuildContext) -> Composition
```

Every scanner section starts with `enabled: Literal["auto", "on", "off"]`:

| Value | Backend present and working | Backend missing or broken |
|---|---|---|
| `auto` | active | `not_installed` or `unavailable`; no effect on verdicts beyond today's behaviour for a broken installed backend |
| `on` | active | `unavailable`; treated as a scanner error on every scan, so `fail_mode` applies |
| `off` | `off`; never constructed | `off` |

`Composition` holds the scanner list (the syntactic scanner first, always) and
one `ScannerStatus(id, state, reason)` per registry entry, where `state` is
`active`, `unavailable`, `not_installed` or `off`. This replaces the
five-outcome status whose `failed` value did not say whether a scanner was
registered.

`BuildContext` carries what a builder cannot get from config, today only the
Semgrep lifecycle owner and scheduling key. Semgrep is an ordinary registry
entry.

`compose` is the only place scanners are constructed from config. The registry
is a literal tuple: there is no third-party scanner discovery. A caller with a
custom scanner passes it to `Pipeline` directly.

Backend constructor knobs are reachable from config or deleted. PromptGuard's
threshold becomes `scanners.prompt_guard.threshold`.

`detects` drives recommendations: with no active `injection` scanner beyond the
syntactic one, `doctor` suggests the `prompt-guard` extra; role `support` or
`admin` without an active `pii` scanner suggests `presidio`.

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

## 7. Hermes binding (provisional)

Fixed now:

- `petasos.hermes.plugin.register(ctx)` builds one `Enforcer`, registers hooks,
  and translates between Hermes hook arguments and `ToolCall` / `Decision`. It
  contains no policy. Target size is a few hundred lines.
- All logic is imported from the installed wheel. Nothing with behaviour is
  copied into a profile directory.
- Settings live in the host's own plugin settings location and are per Hermes
  profile. Secrets go where the host keeps secrets.
- `manifest.py` generates the plugin manifest, including the settings schema
  for `basic` fields (`enabled`, `role`, `level`) and the two secrets, from
  `describe()`.
- `petasos doctor` replaces `verify.py`: install state, hook registration,
  scanner states, resolved settings with origins, recommendations.
- `petasos hermes install` does whatever per-profile setup the host needs.

Open until the plugin-surface report lands:

- Discovery: pip entry point, a generated stub directory holding only a
  manifest and a one-line import, or something newer. At the 2026-10-15 pin a
  settings schema was honoured only for directory plugins.
- The exact settings path and read/write API, and whether it survives the UI
  model switcher, config migrations and `hermes doctor --fix`.
- Which hooks can block or rewrite, and what the host does when one raises or
  times out. This decides which paths can fail closed.
- Whether to keep a compatibility path for the older fork that has no settings
  API (reading the same path from `config.yaml` directly).

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
| B3 | `scanners/registry.py`; scanner sections beside their scanners | B1; parallel with B2 |
| B4 | Cutover: every component takes its own section; old `config.py`, profiles and presets deleted | B2, B3 |

B4 is one lane. Acceptance is verdict parity against the Wave 0 fixture under
the role and level mapping in section 4.2, with the `research` and `admin`
tier change as the only permitted difference.

**Wave C. Structure (parallel after B4)**

| Package | Scope |
|---|---|
| C1 | `enforce/`: extract the plugin's policy and lifecycle into `Enforcer` |
| C2 | `hermes/` and `cli.py`: adapter, manifest, doctor, install. Needs C1's interface and the plugin-surface report |
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

1. Everything listed as open in section 7.
2. Whether `scanners.presidio.score_threshold` and the entity lists can become
   live-appliable cheaply, or stay `restart`.
3. Whether the console keeps a settings editor once the host renders one, or
   becomes activity and diagnostics only. Decide after the researcher soak.
