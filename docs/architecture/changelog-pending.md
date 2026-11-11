# Pending changelog entries

Entries for the redesign, held here until 0.5.0 ships. `CHANGELOG.md`'s
`[Unreleased]` section belongs to the 0.5.0 release work, so writing there from
this branch would conflict with it. When the branch is rebased onto the
released tree, these move into a new `[Unreleased]` section and this file is
deleted.

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
  `approvals.mode: manual`. Under `smart`, Hermes's default, a model can
  approve the command with nobody asked, so Petasos still asks.

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
