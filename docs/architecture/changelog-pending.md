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

- **Breaking.** A tool call that changes a Petasos or Hermes guardrail is no
  longer allowed just because the conversation is below tier 2. `tools.self_change`
  is `approve` or `never` (default `approve`; the support role sets `never`).
  `approve` asks a person, and a session approval lasts `tools.self_change_minutes`
  (default 30, maximum 1440). `never` refuses the change. The operator still
  changes settings from outside the agent. Records of the old "not stopped"
  attempts stay as they were.



- `Severity.rank` is the one severity scale: info is 0, critical is 4, higher
  is more severe. Six hand-written copies of the ordering are gone. Finding
  comparisons behave as before.
