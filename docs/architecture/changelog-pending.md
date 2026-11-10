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
  `[all]` is unchanged (`presidio`, `prompt-guard`, `console`). Either id in
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

## Changed

- `Severity.rank` is the one severity scale: info is 0, critical is 4, higher
  is more severe. Six hand-written copies of the ordering are gone. Finding
  comparisons behave as before.
