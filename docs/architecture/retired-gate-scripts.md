# Retired gate scripts

Working record for removing `scripts/hermes_composition_gate.py`,
`scripts/hermes_multiprofile_harness.py`, and `tests/test_composition_gate.py`.
The two scripts drove the deleted reference plugin and the deleted console
against a Hermes root. The unit test pinned the scripts' own classifiers,
redaction, and preflight. It did not start Hermes.

A parity row cited as `test_enforcer_matches_record[<id>]` is
`tests/enforce_parity/test_enforce_parity.py`. The same id is also replayed
by `test_hermes_adapter_matches_record[<id>]`.

Near-identical cases are one row. "Still exists" means the behaviour is
part of the current plugin, enforcer, or Hermes home, not only of the
deleted files. A gate procedure that existed to keep a hand run off a live
home is not that behaviour.

## What the scripts checked

| Check | What it verified | Still exists | Where it is pinned |
|---|---|---|---|
| Live-root stop | The probe's `HERMES_HOME` is not the live checkout, and the PyYAML it imported was not loaded from that checkout. A hit exited 4 and wrote no evidence. | The sandbox boundary still refuses a home outside the sandbox. The live-checkout borrow does not. | `tests/hermes_host/test_home_guard.py::test_wrapper_refuses_a_home_outside_the_sandbox`, `test_a_chosen_home_is_the_one_hermes_resolves` |
| Which `petasos` a child imports | The composition gate required `petasos.__file__` under `<HERMES_HOME>/installs`, not under the source tree, at version 0.5.0. The older harness required the source tree, because it injected a `.pth`. A dashboard child for a second profile had to report the same file, its own `HERMES_HOME`, and a pid other than the parent. | The committed environment is what a later `hermes` process imports. The 0.5.0 pin and the dashboard child are gone. The environment tests check that the path contains `site-packages`, which the sandbox virtualenv also does. | not covered. Carried by `tests/hermes_host/test_imported_copy.py::test_a_new_process_imports_the_wheel_under_the_homes_installs` |
| Wheel bytes | Every `petasos/` member of `petasos-0.5.0-py3-none-any.whl` matched the release tree and the files Hermes installed. | No. This tree is 0.4.0. The gate was a release-candidate check. | |
| Plugin discovered from the home | Hermes loaded `plugins/petasos` from the launch home, and again for a profile created later and given its own copy. | Yes. | `tests/hermes_host/test_petasos.py::test_plugin_validates_and_loads`, `test_reload_and_a_second_profile_keep_enforcement`; `tests/hermes_host/test_discovery.py::test_directory_plugin_validates_and_loads`; `tests/hermes_host/test_plugin_admission.py::test_every_admission_check_passes_on_the_shipped_directory` |
| Each home binds its own config | The launch process bound the root `config.yaml`. A profile scope bound that profile's file at tier `override`. A child whose `HERMES_HOME` was the profile resolved tier `hermes_home` to the same file. The armed-resolution log named the file. | Yes. | `tests/hermes/test_plugin.py::test_register_logs_the_home_it_bound`; `tests/hermes/test_home.py::test_override_present_resolves_override_tier`, `test_override_absent_with_hermes_home_is_hermes_home`; `tests/hermes_host/test_petasos.py::test_reload_and_a_second_profile_keep_enforcement` |
| Plugin identity line | `agent.log` contained `PETASOS_PLUGIN_IDENTITY`. `verify.py` parsed it, and the digest was 64 hex characters, not redacted. | No. `verify.py` is deleted. `petasos doctor` is the report that replaced it. | |
| Manifest winner versus the console predictor | Hermes's manifest winner and `petasos.console` `protection_status` agreed for an absent folder, one folder, a `.bak` sibling, a nameless or empty or malformed manifest, a folder that claims another name, `__pycache__`, a foreign harness directory, duplicate and merge keys, and a nested copy. | No. The console predictor is deleted. | |
| One module object per profile | The launch home and three profiles were four distinct module objects. | No. One module serves every home. Each home has its own enforcer. | `tests/hermes/test_plugin.py::test_each_home_has_its_own_enforcer` |
| One profile's arming does not change another's | Disabling one profile, then the root, left the others blocking. Turning the profile back on restored only that profile. Settings written on one home stayed off the other. | Yes. | `tests/hermes/test_plugin.py::test_each_home_has_its_own_enforcer`; `tests/hermes_host/test_petasos.py::test_reload_and_a_second_profile_keep_enforcement` |
| Concurrent turns do not cross | Twenty-five overlapping turns on three homes kept each home's decision, and no worker raised. | Yes. The single-enforcer concurrent test does not use two homes. | not covered. Carried by `tests/hermes_host/test_profile_isolation.py::test_concurrent_turns_stay_on_the_profile_that_ran_them` |
| Spool rows stay in the home that handled the turn | A session id landed only in that home's spool. A turn on one profile did not change another home's spool bytes. A disarmed profile's bypass row was signed and stayed in its file. | Yes. Signing itself is pinned. Which file a real Hermes process writes is not. | not covered. Carried by `tests/hermes_host/test_profile_isolation.py::test_a_turn_on_one_profile_does_not_touch_the_other_spool`. Signing: `tests/enforce/test_events.py::test_a_keyed_write_stamps_a_signature_and_an_unkeyed_write_does_not` |
| Owned paths cover sibling profiles | Under one profile, the guard's owned set included that profile's config and spool and the root and sibling profiles' config and spool. | Yes. | `tests/test_selfmod_detection.py::test_gibson_guard_owns_root_config_and_sibling_spool` |
| Old dashboard profile routes | `GET` and `POST` of `/api/plugins/petasos/armed`, `config`, `health`, and `scan-history` with `?profile=` read and wrote only that profile. `default` was the root. An unknown name was not 200. An empty `plugins.enabled` was 404. A backup copy read as shadowed. A profile with no copy read as `no_copy`. | No. Those routes belonged to the deleted console. The tab follows the active home, and the two switches are separate. | `tests/hermes/dashboard/test_router.py::test_status_and_settings_follow_the_active_home`; `tests/hermes/dashboard/test_status.py::test_both_switches_on_is_protection_on`, `test_a_paused_switch_says_which_one_is_off`, `test_hermes_disabled_list_is_the_other_switch` |
| A profile with no plugin copy | Ops, with no `plugins/petasos` of its own, was served by the root's copy and ops's config. | No. That was the old multiplex host. A home without the plugin is not protected. | `tests/hermes/test_doctor.py::test_fresh_home_is_not_protected` |
| Secrets stay out of settings and out of printed output | The copied section dropped `hash_key`, `session_secret`, and unknown keys. The printed session environment did not contain the secret value. Evidence dropped `sig`. | Yes. The allowlist copy was gate procedure. The product rule remains. | `tests/hermes_host/test_petasos.py::test_secrets_come_from_the_env_file`; `tests/hermes/dashboard/test_changes.py::test_secrets_are_not_accepted`; `tests/hermes/dashboard/test_catalog.py::test_a_secret_in_the_stored_document_is_not_returned`; `tests/hermes/test_doctor.py::test_secret_values_are_never_printed`; `tests/hermes_host/test_cli.py::test_migrate_write_is_what_hermes_reads`; `tests/enforce/test_credential_record.py::test_the_signed_approval_line_does_not_contain_the_secret` |
| A real home signs with the env secret | Each spool row verified under `PETASOS_SESSION_SECRET` and failed under a different constant. | Yes. The derivation is pinned on a temporary file. A Hermes home's `.env` is not what those tests sign with. | not covered. Carried by `tests/hermes_host/test_profile_isolation.py::test_the_env_file_secret_signs_the_spool` |
| Corpus decisions, three profiles | For each of C01–C08 and R01–R06, on `default`, `gibson`, and `ops`, the directive or return class, the rule id, the degraded flag, and the single spool row matched the corpus, and the session did not appear in another home. `ops` had the tool guard off, so its pre-call cases passed. | The composed Presidio and PromptGuard decisions need those backends. The syntactic cases are already pinned without them. | Needs real scanners. Syntactic cousins: `test_enforcer_matches_record` for `ready-clean`, `profile-code_generation`, `pii-and-sinks`, `tool-results`, `syntactic-families`; `tests/hermes_host/test_petasos.py::test_injection_is_blocked_and_settings_change_live`, `test_tool_result_with_a_finding_is_annotated`; `tests/enforce/test_decisions.py::test_taint_blocks_ahead_of_pii_and_pii_blocks_only_on_egress`, `test_command_rule_approves_only_when_the_directive_is_usable` |
| Per-profile confidence margin | Each home's own Presidio or PromptGuard scanner scored the calibrated payload at or above the recorded minimum. One home's pass did not stand in for another. | Only with the real scanners. | Needs real scanners |
| Cold-first calls | Eight concurrent first calls stayed under 30 seconds, wrote at most one cold-start marker, and a fail-mode quarantine was acceptable only for `closed` and `degraded`. An `init_failed` row or the Hermes timeout message failed the call. | The decision rules are pinned. The eight-wide first load of the real backends is not. | `test_enforcer_matches_record` for `cold-degraded`, `cold-open`, `cold-closed`, `init-failed-open`, `init-failed-degraded`, `init-failed-closed`; `tests/enforce/test_enforcer.py::test_starting_uses_the_fallback_until_init_is_released`, `test_failed_init_blocks_under_degraded_and_names_the_error`, `test_eval_timeout_is_bounded_by_the_supplied_deadline`. The timed backend load is Needs real scanners. |
| Warmup until the backends are healthy | Usable Presidio and PromptGuard reached `healthy` with a `last_ms`, within 180 seconds, before the corpus ran. | Only with the real scanners. | Needs real scanners |
| Scanner ground truth | Disabled, package-absent, and usable backends matched the build outcome and the runtime health row. Semgrep with no lifecycle owner was `failed` / `semgrep.host_lifecycle_unavailable`, was not registered, and left no Semgrep rule on a spool row. The console health column showed the same. | The Semgrep refusal, a missing package, and a disabled scanner are pinned. A usable Presidio or PromptGuard row needs the packages. The console column was the deleted console. | `tests/scanners/test_registry.py` (the `semgrep.host_lifecycle_unavailable` cases); `tests/hermes/test_doctor.py::test_unavailable_scanner_is_named`; `tests/test_pipeline_health.py::test_scanner_health_reports_each_status`; `tests/hermes/dashboard/test_status.py` (a check that is on and cannot run). Usable rows: Needs real scanners. |
| Missing PromptGuard cache | With the hub cache pointed at an empty directory, `closed` and `degraded` blocked with `param_scan_degraded` and no rule id, `open` passed, and a disabled tool guard passed. Health showed PromptGuard unavailable with an error. | Yes, on the base install. | `tests/enforce/test_enforcer.py::test_missing_scanner_auto_is_quiet_and_on_degrades`; `tests/enforce/test_fallback.py::test_fail_mode_allows_only_a_clean_open_scan`; `tests/enforce/test_decisions.py::test_degraded_scan_ladder`; `test_enforcer_matches_record[backends-missing]` |
| Approve posture | When a profile's posture was approve, one fetch-exec call was answered inside Hermes's notify callback. The spool was exactly a request row then a response row, both signed, choice `once`, and the hook returned no block. | Yes. Today's corpus did not exercise it; the enforcer and the host tests do. | `tests/hermes_host/test_petasos.py::test_approve_follows_the_host_state`; `test_enforcer_matches_record[approval-observation]`; `tests/enforce/test_approvals.py::test_approval_fields_and_event` |
| Hook bound and host skip | A call at or over 30 seconds, or Hermes's "timed out or is still running" message, failed that call. A skip line failed only the stage that logged it. Recorded timings did not change the verdict. | The timeout message and a bounded wait are pinned. The scripts' timing log was measurement only. | `tests/hermes_host/test_hooks.py::test_pre_tool_call_raise_and_timeout`; `tests/enforce/test_enforcer.py::test_eval_timeout_is_bounded_by_the_supplied_deadline` |
| Benign load | Eight workers, five rounds of a clean pre-call and a clean tool result, wrote no spool row and raised no worker. | Yes, without the optional scanners. | `tests/enforce/test_enforcer.py::test_concurrent_calls_all_return_a_decision`; `test_enforcer_matches_record[ready-clean]` |
| Cold scanner delivery and cancel | The first Presidio scan and the first PromptGuard scan hit a 0.05 second timeout while loading. The following scan found `petasos.presidio.email_address` or `petasos.promptguard.injection`. Seven of eight queued PromptGuard scans cancelled, the one that ran found the injection rule, and a scan after that still found it. | Only with the real scanners and the cached weights. | Needs real scanners |
| Weight snapshot is unchanged | The PromptGuard snapshot was complete before the run, the file list and sizes were the same after, and the environment was offline with no Hugging Face token. | Only with a real snapshot. The run must not download weights. | Needs real scanners |
| Optional packages import | Stage 1 imported `presidio_analyzer`, `presidio_anonymizer`, `torch`, `transformers`, and `en_core_web_lg`. | Only with those packages installed. | Needs real scanners |
| Isolated tool store | Hermes's resolved store Python sat inside the isolated root's `tools/`, including when the path was spelled with the `\\?\` prefix. Bootstrap did not disable the plugin. | No. That store belonged to the Hermes 0.22.5 root the gate borrowed. The sandbox virtualenv is the interpreter these tests use. | |
| Evidence hygiene and preflight | Path spellings (including Windows extended and doubled forms), the host name, and the user name as a path segment were rewritten or the evidence was refused. The write was atomic. Exit 2 was preflight, 4 was the live-root stop, 5 was the sweep, 6 was an unexpected error. A label outside `[a-z0-9-]+`, a workdir with a space or a comma, a workdir that resolved inside or around the live root, a `tools/` link that left the isolated root, a driver schema that differed from the release tree, and a stale evidence file were all refused. Info, timing, and an unexercised approval did not fail the verdict. A probe that died kept its last check. | No. This is the gate's own bookkeeping. | |
| Spool reader | Lines at or before a start count were ignored. A torn line and a non-object were reported with 1-based line numbers, and well-formed objects were still returned. | The product reader skips corrupt and partial lines. The gate's line-number report was for its evidence file. | `tests/hermes/dashboard/test_activity.py::test_corrupt_and_partial_lines_are_skipped` |
| Live matrix selection | Named profiles were read and not written. A profile was included only with a `petasos:` section and a plugin copy, and not when `gateway.parked` was present. Missing config, bad YAML, no section, and no copy were excluded by reason. | No. The gate was choosing which live homes to copy. Profile listing that still exists does not apply those filters. | `tests/hermes/test_home.py::test_list_hermes_profiles_enumerates_and_marks_active`, `test_a_bad_profile_pointer_falls_back_to_root` |
| Planned call ids | Every planned hook call had its own `tool_call_id` and `turn_id`, and `task_id` equalled `session_id`, so Hermes would not collapse two calls. | The host forwards those ids. The planner was the gate's. | `tests/hermes_host/test_hooks.py::test_pre_tool_call_block_none_and_unknown` |
| Probe process cleanup | Child output was decoded as UTF-8. A grandchild holding the pipes could not keep the call past its bound. POSIX killed the process group. Windows used `taskkill /T`. | No. The sandbox reap stops processes whose environment names the sandbox. | `tests/hermes_host/conftest.py` session reap |

## Needs real scanners

These need Presidio, PromptGuard, and the cached PromptGuard snapshot. They
are not written here. `tests/test_scanner_composition.py` is the opt-in
scanner test and is owned by another change. Do not download weights to
run these.

- On one Hermes process, for each of profiles `default` (fail closed, tool
  guard on), `gibson` (the same), and `ops` (tool guard off), replay
  `scripts/hermes_composition_corpus.json` cases C01–C08 and R01–R06.
  C04 and R03 are letter-spaced injection and must be
  `petasos.promptguard.injection` only. C05 and R02 must match either that
  rule or `petasos.syntactic.injection.ignore-previous`. C06 must be
  `petasos.presidio.email_address` on `send_email` and must not block the
  same address on `write_file` (C07). R05 (PII only, in a result) and R06
  (`write_file` result) stay clean. `ops` pre-call cases pass because the
  guard is off. Each case writes one spool row in that profile's file and
  none in the others. Each profile's own scanner, not a sibling's, meets
  the case's recorded minimum confidence.
- The first Presidio scan and the first PromptGuard scan of a cold process
  do not finish inside 0.05 seconds. The next Presidio scan finds
  `petasos.presidio.email_address`. The next PromptGuard scan, after the
  warmup error if the model is still loading, finds
  `petasos.promptguard.injection`. Seven of eight queued PromptGuard scans
  cancel, the one left running finds that rule, and a scan after the
  cancel still finds it.
- With both packages present and the snapshot complete, runtime health for
  Presidio and PromptGuard is `healthy` and carries `last_ms`. With the hub
  cache pointed at an empty directory, PromptGuard is `unavailable` with a
  non-empty error, and a `closed` or `degraded` profile blocks a benign
  command as a degraded parameter scan with no rule id.
- The snapshot directory's file list and sizes are the same after the run
  as before. The run sets `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` and
  does not read a Hugging Face token.

## Needs Windows

No product check was left that only Windows can run.

The scripts' Windows-only machinery was the gate's, and it is not carried:

- `taskkill /T /F` to end a probe and the children it started.
- Comparing a store path that Hermes spelled with the `\\?\` prefix to the
  isolated root's `tools/` directory.
- Refusing a junction planted at the isolated root, or at `tools/`, that
  resolved into the live Hermes root. The same containment on a symlink is
  what the deleted unit test ran here, and it was gate preflight, not
  plugin behaviour.

Home resolution on Windows is already
`tests/hermes/test_home.py::test_windows_root_uses_localappdata_and_absorbs_a_missing_home`.
Percent-sign expansion of an override is
`test_override_expands_user_and_vars`, which records that `%VAR%` expands
only on Windows.
