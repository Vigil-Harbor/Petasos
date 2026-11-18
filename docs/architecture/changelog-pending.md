# Pending changelog entries

Entries for the redesign, held here until 0.5.0 ships. `CHANGELOG.md`'s
`[Unreleased]` section belongs to the 0.5.0 release work, so writing there from
this branch would conflict with it. When the branch is rebased onto the
released tree, these move into a new `[Unreleased]` section and this file is
deleted.

## Added

- PET-267: flagged tool results record the conversation risk score and its tier;
  Activity shows both. Signed older records remain readable and verifiable.

- PET-265: development installs keep each wheel under its content digest, so a
  newer build with the same version reaches new Hermes processes through normal
  admission. Old wheels remain until Hermes accepts the new build, then are
  removed. Doctor warns when the committed environment still runs an older
  build and gives `hermes petasos refresh` for that home. Refresh rebuilds
  Hermes's environment from the saved wheel without turning the plugin off
  or rewriting its files. Install now says when the earlier build still checks
  tool calls and exits 1 when the new build is saved but not yet running.
  Builds predating refresh need disable-then-enable one last time to make the
  command available; the operator decides when to do that transition.

- Beside a loaded Tirith plugin, asking roles leave terminal pipes to a shell,
  decoded execution and fetched execution to Tirith. Petasos still blocks in
  blocking roles and when approvals would run unattended, and retains all
  other protection. Mixed findings need an owner for each rule. Activity,
  Try it and doctor explain who checks the command; result notes are unchanged.

- Reference pages generated from the settings schema, layer tables, scanner registry and command parsers; rewritten Hermes and library guides with executable examples and relative-link checks.

- Try it shows the pipeline's text with selected personal information hidden, a redacted preview, and this input's conversation risk with the tried thresholds; each trial stays private and disposable. The Petasos tab shows its version beside Checked and Refresh.

## Removed

- **Breaking.** `LlmGuardScanner`, `LlamaFirewallScanner`, and the `llm-guard`
  and `llamafirewall` extras. Their CI lanes, their rule ids
  (`petasos.llmguard.*`, `petasos.llamafirewall.*`) and CodeShield go with
  them. `PromptGuardScanner` is the injection backend. The `code_generation`
  profile still downgrades `petasos.promptguard.injection` to non-blocking.
  `[all]` is `presidio` and `prompt-guard`. Either id in
  `disabled_scanners` is now rejected as unknown.
- **Breaking.** The license machinery. `LicenseClaims`, `LicenseState`,
  `LicenseValidator` and `validate_license` are no longer exported;
  `Pipeline.activate` and `Pipeline.deactivate` are gone; `PETASOS_LICENSE_KEY`
  is not read. Every feature remains free and controlled by config. The console
  about payload no longer includes `license`, and the documented
  `/api/activate` and `/api/deactivate` operations are removed.
- The `pyjwt` dependency. The base install has no third-party dependencies.
- One-off ticket scripts and their fixtures: `scripts/pet135_replay.py`,
  `scripts/pet242_copy_footprint.py`, `scripts/pet184_dispatch/`,
  `scripts/pet200_calibrate.py`, `tests/test_pet200_calibration.py`,
  `tests/fixtures/pet200/`.
- Tracked archives under `docs/specs/`. The directory stays gitignored.
- `assets/petasos-shield.svg`, which nothing referenced.
- `tests/test_config_surface_honesty.py`, which pinned `file:line` anchors
  into package source.
- `Pipeline.scanner_health()` no longer calls a duck-typed `load_health()`
  method. No bundled scanner implemented it. A backend that is installed but
  failed to load still reports `error`; `degraded` still covers scan errors
  and timeouts.
- **Breaking.** The reference plugin, `docs/deployment/reference_plugin/`.
  Enforcement is `petasos.enforce`. The Hermes adapter is `petasos hermes install`
  and `petasos doctor`. The enforcement record in
  `tests/enforce_parity/outcomes.json` is frozen and can no longer be regenerated.
- **Breaking.** The standalone console, `petasos/console/`, the `petasos-console`
  script, and the `console` extra. `uvicorn` leaves with the console. FastAPI
  stays in the `dev` extra because the dashboard tests import it; Hermes supplies
  it in a real install. The operator surface is the Petasos tab in Hermes's
  dashboard.

- **Breaking.** The flat `PetasosConfig`, `ProfileResolver`, `ResolvedProfile`,
  and `TierThresholds`. `from petasos import PetasosConfig` is the config tree.
  Build one with `PetasosConfig()`, `from_mapping`, or `resolve` (a role, a
  level, and overrides). Roles are `general`, `coding`, `research`, `support`, and
  `admin` (the old `code_generation` and `customer_service` names). An old
  settings document, including `profile_name`, is converted by
  `petasos config migrate`.
- **Breaking.** `profile` on `Pipeline`, `Pipeline.inspect`,
  `Pipeline.reconfigure`, and `ToolCallGuard`. A pipeline is bound to one tree.
  Pass the resolved config to the constructor. `Pipeline.list_profiles` and
  `default_profile` are gone.
- **Breaking.** `legacy_config` on the pipeline, the guard, the frequency
  tracker, the audit emitter, the alert manager, the lineage registry, and the
  taint store. `apply_config` no longer takes `legacy`. Reconfigure with a tree.
  `session_secret` and `hash_key` are `Secrets` passed beside the config, not
  fields. Hash mode with no hash key is still rejected where the two meet.
- **Breaking.** `petasos.scanners.build_scanners`, `ScannerBuildStatus`, and
  `ScannerOutcome`. Build scanners with
  `petasos.scanners.registry.compose(config, BuildContext())`.

## Changed

- PET-269: doctor's default job row gives the job, strictness and one short
  explanation. Per-setting explanations remain available in verbose output
  and JSON.

- PET-268: doctor lists only live Hermes profiles, including profiles identified
  by markers other than config.yaml. Guardrails keep the parent profiles
  directory protected so first writes and newly created profiles are noticed.

- `petasos hermes pin` and `unpin` preview and optionally prepare managed
  settings and plugin-list changes without invoking administrator rights.
  A pin holds both plugin lists, the plugin-check time limit and every
  Petasos setting, and applies to every profile on the machine. While one is
  in force Petasos uses the pinned settings and nothing a profile holds, and
  the settings form and `petasos config set` refuse to save. Doctor and the
  Overview show pinned, partly pinned, writable, bypassed and changed-profile
  states.

- **Breaking.** The `general` role sets `tools.dangerous_posture` to `approve`.
  A risky tool call is put to a person when one can be asked, and blocked when
  nobody can. `research`, `support`, and `admin` still block. `petasos config
  migrate` writes `tools.dangerous_posture: block` for a configuration converted
  from the old `general` profile, and says so. An upgrade does not start asking
  unless that setting is changed. A configuration that already names a posture
  keeps it.
- On a `terminal` command, when the posture is `approve` and the decision would
  have been a command-rule finding, Petasos records the finding and stands aside
  if Hermes's own detector flags the command and Hermes will ask a person.
  Hermes's prompt is the one the person sees. The session score is unchanged.
  A block posture still blocks. Taint, another finding, PII leaving through an
  egress sink, and a degraded parameter scan are decided as before. A command
  Hermes does not flag, or would approve or refuse without asking, stays
  Petasos's own decision. If Hermes's detector cannot be imported, has moved,
  or raises, Petasos decides as it does today. This applies under
  `approvals.mode: manual`. Smart-mode ownership is now tier-dependent, as
  recorded in the smart-approval note below.

- **Breaking.** A tool call that changes a Petasos or Hermes guardrail is no
  longer allowed just because the conversation is below tier 2. `tools.self_change`
  is `approve` or `never` (default `approve`; the support role sets `never`).
  `approve` asks a person, and a session approval lasts `tools.self_change_minutes`
  (default 30, maximum 1440). `never` refuses the change. The operator still
  changes settings from outside the agent. Records of the old "not stopped"
  attempts stay as they were.



- Semgrep cannot be turned on inside Hermes, because nothing there runs its
  engine yet. `on` and `auto` both ask for a check that cannot start, and
  under the usual fail mode that blocks tool calls that change things. The
  settings form offers only Never, every save that would leave Semgrep on is
  refused, `petasos scanner add semgrep` is refused, and `petasos doctor`
  says Semgrep cannot run there yet and gives the command that turns it off.
  A hand-written `on` or `auto` is left as it is and still blocks.
- New command `petasos config set <setting> <value>` (also `hermes petasos
  config set`). It changes one simple setting through Hermes, with the same
  checks as the settings form, and says when the change takes effect.
- `Severity.rank` is the one severity scale: info is 0, critical is 4, higher
  is more severe. Six hand-written copies of the ordering are gone. Finding
  comparisons behave as before.
- A tool result handed over as a JSON document is read line by line. Hermes
  returns most results as JSON text, where a line break inside a string is
  written as backslash and `n`, so a whole file read counted as one line. A
  rule that asks whether things share a line then flagged ordinary pages, and
  a phrase broken over two lines was missed. Each written line break is now
  read as one. Plain text results are scanned as before.
- The rule for text that tells an agent to fetch or install something now
  needs its three parts within 300 characters of each other on the line. A
  long paragraph that mentions an agent, a command word and a link somewhere
  is no longer flagged. A directive padded past that distance is not caught.
- The nesting-depth check counts brackets only across unbroken JSON
  structure. A character that cannot appear in JSON outside a string ends
  the run, so the brackets of program code and shell commands are no longer
  read as deeply nested JSON. Deep JSON is still found anywhere in the text,
  closed or not.

## Import paths

- **Breaking.** Module splits remove the old implementation modules; no
  compatibility modules remain. These are the owning import paths:

  | Old | New |
  |---|---|
  | `petasos._types` | `petasos.model` |
  | `petasos._coverage` | `petasos.coverage` |
  | `petasos._limits` | `petasos.limits` |
  | `petasos.session._safe_json` | `petasos.session.safe_json` |
  | `petasos.pipeline` implementation | `petasos.pipeline.pipeline` (orchestration), `petasos.pipeline.findings` (merge, suppression, floors, safe and coverage computation), `petasos.pipeline.health` (timeouts, breaker and health) |
  | `petasos.session.ingest` | `petasos.pipeline.ingest` |
  | `petasos.session.guard` | `petasos.guard.guard` (guard and result), `petasos.guard.tools` (tool table and aliases), `petasos.guard.params` (rendering and scan constants), `petasos.guard.selfmod` (classification and depth sentinel), `petasos.guard.fanout` (`SpawnBudget`) |
  | `petasos.session.guardrail` | `petasos.guard.guardrail` (`recognize`), `petasos.guard.surface` (surface types, library rules and package roots), `petasos.guard.paths` (`normalize_path_text` and path matching), `petasos.guard.shell`, `petasos.guard.shell_parse`, `petasos.guard.mutations`, `petasos.guard.program`, `petasos.guard.bounds` |
  | `petasos.scanners.minimal` implementation | `petasos.scanners.minimal.scanner`, `.taxonomy`, `.injection`, `.command`, `.role_switch`, `.agent_directive`, `.structural`, `.encoding`, `.decode`, `.views` |
  | `petasos.scanners.semgrep` implementation | `petasos.scanners.semgrep.adapter` |
  | `petasos.scanners._semgrep_engine` | `petasos.scanners.semgrep.engine` |
  | `petasos.scanners._semgrep_process` | `petasos.scanners.semgrep.process` |
  | `petasos.scanners._semgrep_runtime` | `petasos.scanners.semgrep.runtime` |
  | `petasos.scanners._semgrep_source` | `petasos.scanners.semgrep.source` |
  | `petasos.scanners._semgrep_roots` | `petasos.scanners.semgrep.roots` |
  | `petasos.scanners._semgrep_qualification` | `petasos.scanners.semgrep.qualification` |

  The package imports `petasos.pipeline.Pipeline`,
  `petasos.scanners.minimal.MinimalScanner` / `RULE_TAXONOMY`, and the five
  names in `petasos.scanners.semgrep.__all__` remain the package APIs. Private
  helpers must be imported from their owning submodule. Semgrep's data moves
  from `scanners/semgrep_rules/` and `scanners/semgrep_qualification.json` to
  `scanners/semgrep/rules/` and `scanners/semgrep/qualification.json`.

- **Breaking.** `petasos.__all__` is exactly the section 9 API. Former root
  exports stay available from their owning submodules: coverage and normalized
  text records from `petasos.model`; message formatters from
  `petasos.enforce.messages`; guard types from `petasos.guard.guard`;
  `RULE_TAXONOMY` from `petasos.scanners.minimal.taxonomy`; Semgrep types and
  closure from `petasos.scanners.semgrep`; ingestion helpers from
  `petasos.pipeline.ingest`; session managers, tokens, tier helpers and stores
  from their `petasos.session` submodules; `normalize` from `petasos.normalize`.
  The root adds `Settings`, `resolve`, `ConfigError`, `Secrets`, `Enforcer`,
  `Decision`, `Allow`, `Block`, `Approve`, and `ToolCall`.

The shared timeout-error prefix moves from `petasos.pipeline._TIMEOUT_ERROR_PREFIX`
to `petasos.model._TIMEOUT_ERROR_PREFIX`. The ingestion head length moves from
`petasos.session.ingest.HEAD_CHARS` to `petasos.limits.HEAD_CHARS`.

- PET-266: built-in strictness levels no longer warn about their own risk
  thresholds. Custom thresholds still receive scan-step diagnostics; relaxed
  keeps its calibrated 25/45/65 values.

- Under Hermes smart approval, plain terminal command findings in an asking role
  are left to Hermes's guardian while the conversation is below tier1. At tier1
  or above, or with an unreadable tier, Petasos asks the person itself. Deferred
  events name the judge and record the conversation score and tier. No setting
  is added; manual approval and Tirith ownership keep their behavior.

- Config set, migration writes and released installs select the home named by
  `--home` or `--profile`, even when another Hermes profile is active.
