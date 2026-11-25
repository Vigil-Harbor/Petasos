# Retired tests

Working record for the removal of the reference plugin and the standalone
console. It is deleted in a later pass. Class A is a test of code that is
going away. Class B is a test of behaviour that is still live, already pinned
by the named test. Class C is a test of behaviour that nothing else pinned;
the new test is the port, and it passes while the old test is still here.

A parity row cited as `test_enforcer_matches_record[<id>]` is
`tests/enforce_parity/test_enforce_parity.py`. The same id is also replayed
by `test_hermes_adapter_matches_record[<id>]`.

## Class C

| Old test | New test | What it protects |
|---|---|---|
| `tests/test_reference_plugin_block_messages.py::test_shim_routes_every_block_site_through_formatter` | `tests/enforce/test_formatter_sites.py::test_every_block_site_calls_a_formatter` | A new block cannot be a hand-written string. The 14 call sites are all in `petasos/enforce`. |
| `tests/test_enforcement_integrity.py::test_keyed_write_produces_nonempty_sig_on_disk`, `test_unkeyed_write_stamps_no_sig`, `test_sig_is_the_only_added_record_field` | `tests/enforce/test_events.py::test_a_keyed_write_stamps_a_signature_and_an_unkeyed_write_does_not`, `test_the_signature_is_the_only_field_signing_adds` | A signed spool line carries a signature and nothing else is added by signing. |
| `tests/test_enforcement_integrity.py::test_verify_event_total_never_raises` | `tests/enforce/test_events.py::test_verify_event_never_raises` | A bad signature input is a failed check, not an exception. |
| `tests/test_enforcement_integrity.py::test_writer_signing_exception_returns_false_and_writes_nothing` | `tests/enforce/test_events.py::test_a_signing_failure_writes_nothing` | A signing failure does not leave a partial line. |
| `tests/test_enforcement_integrity.py::test_key_derivation_deterministic_and_domain_separated` | `tests/enforce/test_events.py::test_the_spool_key_is_domain_separated` | The spool key is not the session secret and not another label's key. |
| `tests/test_enforcement_events.py::test_path_keyed_spool_key_and_fallback` | `tests/enforce/test_events.py::test_a_path_keeps_its_own_key` | Two spool files in one process do not share a signing key. |
| `tests/test_enforcement_events.py::test_orphan_rot_recovered_not_overwritten`, `test_reader_rotation_captures_inflight_and_no_doublecount` | `tests/enforce/test_events.py::test_rotation_refuses_to_overwrite_a_leftover`, `test_a_drain_reads_each_complete_line_once` | Rotation will not destroy an undrained `.rot`, and a torn last line is read once it is finished. |
| `tests/test_reference_plugin_cold_start.py::test_cold_start_degraded_emitted_once_per_session`, `test_failed_spool_write_does_not_consume_the_latch`, `test_uncorrelatable_session_emits_exactly_once_per_process`, `test_latch_is_capped` | `tests/enforce/test_cold_latch.py::test_a_session_gets_one_marker_until_it_is_released`, `test_an_anonymous_marker_is_once_per_book`, `test_the_marker_table_is_capped` | A cold-start marker is issued once, returned if the write failed, and the table cannot grow without bound. Each enforcer has its own book. |
| `tests/test_pet250_credential_reporting.py::test_approval_redacted_before_clipping_signing_and_history` | `tests/enforce/test_credential_record.py::test_the_signed_approval_line_does_not_contain_the_secret` | The signed spool line contains the mask, not the secret. The console history half of the old test is class A. |
| `tests/test_audit_finding_sink.py` (the `TestPerFindingSink` cases that call `_PLUGIN._handle_audit`) | `tests/enforce/test_audit_findings.py::test_emit_findings_writes_one_line_per_finding`, `test_a_safe_result_is_still_recorded_when_the_toggle_is_on`, `test_findings_are_not_logged_unless_the_toggle_is_on` | PET-136: one audit line per finding when the toggle is on, including an allowed result, and none when it is off. |
| `tests/test_console_handlers.py` health and profile tests (`test_pipeline_scanner_health`, `test_pipeline_list_profiles`, `test_health_*`) | `tests/test_pipeline_health.py` | `Pipeline.scanner_health` statuses, the Semgrep warning, and `list_profiles`. |
| Flat `Pipeline.reconfigure`, `legacy_config`, and the session `apply_config(legacy=...)` branches the console save used | `tests/test_pipeline_health.py::test_flat_reconfigure_keeps_the_secret_and_names_semgrep`, `test_flat_apply_keeps_an_explicit_legacy_on_the_session_objects` | A flat save keeps the session secret, logs a Semgrep change, and a classifier error does not raise. |
| `tests/test_console_validation.py` tier, wait, and sink rejects | `tests/test_pipeline_health.py::test_flat_config_rejects_a_low_tier_a_long_wait_and_a_blank_sink` | The flat config still rejects those values. |
| Console sort and about serialization (`severity_rank(..., unknown_wins=True)`, `AuditEvent.to_dict`, `Alert.to_dict`) | `tests/test_pipeline_health.py::test_unknown_severity_and_audit_dicts_round_trip` | An unknown severity ranks, and audit payloads become plain dicts. |
| Ingest failure paths reached through the plugin's result hook | `tests/test_pipeline_health.py::test_ingestion_failures_are_recorded_and_do_not_raise` | A bad config, a lock error, and an unreadable head are recorded, not raised. |
| `read_petasos_section`, the Windows root, and a dangling profile pointer | `tests/hermes/test_home.py::test_windows_root_uses_localappdata_and_absorbs_a_missing_home`, `test_a_bad_profile_pointer_falls_back_to_root`, `test_petasos_section_read_distinguishes_empty_from_broken` | Home resolution and the section read still fail soft. |
| `emit_console_event`, `set_spool_key` without a path, `classify_integrity_failure`, `spool_size`, drain of a missing file | `tests/enforce/test_events.py::test_module_key_sig_class_and_console_row` | The module writer still signs, names a missing signature, and fails soft. |
| Excerpt budget and fail-closed paths in the approval observer | `tests/enforce/test_approvals.py::test_excerpt_withholds_what_it_cannot_bound` | An excerpt that cannot be bounded is withheld. |
| Fallback truncation log and a scan that raises | `tests/enforce/test_fallback.py::test_a_truncated_parameter_is_logged_and_a_raising_scan_is_errored` | Truncation is logged and a raising scan is errored, not a block. |
| Presidio `availability` cause and `_ensure_loaded` retry | `tests/test_presidio_scanner.py::test_availability_names_a_crash_a_missing_package_and_a_present_one`, `test_a_retryable_load_is_retried_and_a_crash_is_raised` | A missing backend, a crash, and a retryable load stay distinct. |

## Class B

| Old test | Covering test |
|---|---|
| `tests/test_reference_plugin_cold_start.py`, except the four latch tests in the class C table | `test_enforcer_matches_record` for `cold-degraded`, `cold-open`, `cold-closed`, `init-failed-open`, `init-failed-degraded`, `init-failed-closed`; `tests/enforce/test_enforcer.py::test_starting_uses_the_fallback_until_init_is_released`, `test_failed_init_blocks_under_degraded_and_names_the_error`, `test_init_finishes_during_the_bounded_wait`, `test_eval_timeout_is_bounded_by_the_supplied_deadline`; `tests/enforce/test_fallback.py::test_fail_mode_allows_only_a_clean_open_scan`, `test_read_only_is_skipped_and_a_finding_blocks`, `test_scan_error_and_exception_are_errored_without_a_block`, `test_unclassifiable_name_fails_secure`. The plugin's process-wide wait flag cannot recur: `InitGate` and `Book` belong to one enforcer (`tests/enforce/test_enforcer.py::test_two_enforcers_do_not_share_decisions`). |
| `tests/test_reference_plugin_block_messages.py` except `test_shim_routes_every_block_site_through_formatter`, `test_shim_imports_formatter`, `test_shim_emits_branding`, `test_manifest_and_runbook_hook_lists_agree` | `tests/enforce/test_messages.py` (`TestTier3BlockMessage`, `TestTier2BlockMessage`, `TestCatchAllBlock`, `TestParamScanUnsafe`, `TestInternalReasonStrings`, `TestPipelineBlockMessage`). |
| `tests/test_reference_plugin_egress.py` | `test_enforcer_matches_record` for `pii-and-sinks` and `taint-fence`; `tests/enforce/test_decisions.py::test_taint_blocks_ahead_of_pii_and_pii_blocks_only_on_egress`. |
| `tests/test_reference_plugin_tool_result.py` | `test_enforcer_matches_record` for `tool-results`, `tool-result-oversized`, `tool-result-error`, `tool-result-timeout`. |
| `tests/test_disarm_bypass_counter.py` | `test_enforcer_matches_record[disarmed-bypass]`; `tests/enforce/test_enforcer.py::test_disarmed_bypass_is_rate_limited_by_the_clock`. |
| `tests/test_param_scan_parity.py` | `tests/enforce/test_decisions.py::test_degraded_scan_ladder`; `test_enforcer_matches_record[scan-timeout-blocks]` and `[backends-missing]`. |
| `tests/test_pet221_approve_posture.py` | `test_enforcer_matches_record` for `posture-approve`, `approve-unavailable`, `auto-approve`, `always-approved`, `degraded-approve-confirm`, `degraded-approve-deny`; `tests/enforce/test_decisions.py::test_posture_normalizes_to_approve_or_block`, `test_command_rule_approves_only_when_the_directive_is_usable`. |
| `tests/test_pet222_approval_observe.py` | `test_enforcer_matches_record` for `approval-observation`, `approval-excerpts`, `approval-redactor-unavailable`; `tests/enforce/test_approvals.py::test_approval_fields_and_event`, `test_excerpt_redacts_and_withholds`. |
| `tests/test_pet227_degraded_rearm.py` | `test_enforcer_matches_record` for `degraded-approve-confirm` and `degraded-approve-deny`; `tests/enforce/test_approvals.py::test_degraded_pending_key`. |
| `tests/test_ingestion_backstop.py::test_published_trajectory_table_shipped`, `test_composed_call_trajectory_shipped`, `test_uncorrelatable_shape_does_not_arm` | The counts are pinned without the plugin by `test_published_trajectory_table_model` and `test_composed_call_trajectory_model` in the same file, which stay. The hook is `test_enforcer_matches_record` for `tool-results`, `uncorrelated-result`, and `tier-climb`. |
| `tests/test_subagent_plugin_wiring.py` | `test_enforcer_matches_record` for `lineage` and `lineage-unavailable`; `tests/hermes/test_plugin.py::test_hook_passes_the_agent_when_the_task_id_is_absent`. |
| `tests/test_multiplex_home.py` | `tests/hermes/test_plugin.py::test_each_home_has_its_own_enforcer`. |
| `tests/test_profile_rebind.py` | The old rebind log lines are an accepted absence (`tests/enforce_parity/differences.json`). The live read is `test_enforcer_matches_record` for `settings-while-running` and `profile-and-arm`, and `tests/hermes/test_settings.py::test_bound_profile_is_read_on_the_next_call`. |
| `tests/test_plugin_api_paths.py` | `tests/hermes/test_home.py::test_default_under_hermes_home`, `test_override_absent_with_hermes_home_is_hermes_home`, `test_resolve_profile_config_path_member_and_traversal`. |
| `tests/test_scanner_composition.py::test_real_scanners_reach_plugin_decisions` | Opt-in (`PETASOS_TEST_SCANNER_COMPOSITION=1`), so the default suite does not collect it. The syntactic and stub decisions are `test_enforcer_matches_record` for `profile-code_generation`, `pii-and-sinks`, and `tool-results`. The real-backend half was not rewritten: it still points at `docs/deployment/reference_plugin/__init__.py`, a public tool-call decision does not return findings, and the test cannot run without the weights. `test_real_scanners_eight_concurrent_calls` and `test_semgrep_composes_with_real_presidio_and_prompt_guard` do not import the plugin and stay. Registry composition without the weights is `tests/scanners/test_registry.py::test_one_composition_covers_registered_and_quiet_states`. |
| `tests/js/console-token.test.mjs` | The console token is dropped (section 8.6). Secret values are refused by `tests/hermes/dashboard/test_changes.py::test_secrets_are_not_accepted` and `tests/hermes/dashboard/test_catalog.py::test_a_secret_in_the_stored_document_is_not_returned`. |
| `tests/js/approval-row.test.mjs`, `tests/js/refused-approvals.test.mjs` (the redaction notice assertions) | `tests/enforce/test_approvals.py::test_display_redaction_and_reason`; `tests/hermes/dashboard/test_activity.py::test_redaction_hides_a_secret_in_the_reason`. The queue itself is class A. |
| `tests/test_enforcement_events.py::test_block_emits_enforcement_event`, `test_allowed_call_emits_no_event`, `test_disarmed_pre_tool_call_runs_no_scan`, `test_armed_pre_tool_call_invokes_guard_evaluate`, `test_bypassed_event_carries_count`, `test_fallback_init_window_block_emits_event` | `test_enforcer_matches_record` for `ready-clean`, `disarmed-bypass`, `cold-degraded`, and `syntactic-families`. |
| `tests/test_benchmarks.py` ingestion cases (`test_benchmark_ingestion_result_1kb` through `test_benchmark_fallback_param_scan_1mb`) | Measure-only. The clipping they mention is `test_enforcer_matches_record[tool-result-oversized]`. They are retargeted to `Enforcer.tool_result` when the plugin file goes, under the same names, so the benchmark list does not shrink. |

## Class A

These test only the deleted console, the deleted plugin file, or `verify.py`.

| Old test | Why it is only the deleted code |
|---|---|
| `tests/js/` except the two redaction rows and `console-token.test.mjs` in class B: `approval-row.test.mjs` (layout half), `arm-scope-view.test.mjs`, `armed-sync.test.mjs`, `cold-start-row.test.mjs`, `config-sections.test.mjs`, `console-modules.test.mjs`, `disarm-bypass-counter.test.mjs`, `enforcement-history.test.mjs`, `enforcement-provenance.test.mjs`, `hermes-diegetic-profile.test.mjs`, `hermes-profile-selector.test.mjs`, `integrity-health.test.mjs`, `playground.test.mjs`, `preset-dial.test.mjs`, `profile-picker.test.mjs`, `profile-scoped-reads.test.mjs`, `protection-banner.test.mjs`, `refused-approvals.test.mjs` (queue half), `richtext.test.mjs`, `scan-history-count.test.mjs`, `scan-history-paging.test.mjs`, `scanner-health.test.mjs`, `selfmod-row.test.mjs`, `selfmod-tile-filter.test.mjs`, `skeleton.test.mjs`, `sse-reconnect.test.mjs`, `trap-burst.test.mjs`, plus `harness.mjs` and `harness-audit.md` | They load `petasos/console/static/` and the old embedded plugin script. |
| `tests/test_sse.py`, `tests/test_ring_buffer.py`, `tests/test_config_meta.py`, `tests/test_presets.py` | The broadcaster, the ring, the field catalogue, and the strength dial. The dial's replacement is roles and levels, already tested by `tests/config/test_sections.py` and `tests/hermes/dashboard/test_catalog.py::test_read_lists_roles_levels_and_resolved_rows`. |
| `tests/test_console_armed.py`, `tests/test_console_armed_write_binding.py`, `tests/test_console_auth.py`, `tests/test_console_handlers.py`, `tests/test_console_hermes_profile.py`, `tests/test_console_integrity_health.py`, `tests/test_console_integrity_preflight.py`, `tests/test_console_packaging_durability.py`, `tests/test_console_playground.py`, `tests/test_console_profile_scoped_reads.py`, `tests/test_console_reload.py`, `tests/test_console_scan_detail.py`, `tests/test_console_scan_history.py`, `tests/test_console_scans_total.py`, `tests/test_console_scoped_routes.py`, `tests/test_console_server.py`, `tests/test_console_sse_route.py`, `tests/test_console_standalone_entrypoint.py`, `tests/test_console_validation.py` | Routes, auth, history, and the standalone entrypoint. Settings refusal, redaction, and activity paging are the class B dashboard tests named above, plus `tests/hermes/dashboard/test_changes.py::test_an_invalid_value_is_refused_and_nothing_is_written` and `test_a_managed_refusal_is_reported_as_such`. |
| `tests/test_plugin_api_sse.py`, `tests/test_plugin_files.py`, `tests/test_verify.py`, `tests/test_reference_plugin_manifest.py`, `tests/test_plugin_init_logging.py`, `tests/assert_console_artifacts.py` | The embedded router, `verify.py`, and the old manifest. `petasos doctor` is `tests/hermes/test_doctor.py`. The new manifest is `tests/hermes/test_manifest.py::test_committed_manifest_matches_the_generator`. |
| `tests/test_pet223_refused_queue.py` | The refused-approvals queue and the reviewed file. That surface has no equivalent. Redaction words are class B. |
| `tests/test_reference_plugin_block_messages.py::test_shim_imports_formatter`, `test_shim_emits_branding`, `test_manifest_and_runbook_hook_lists_agree` | They read the plugin source and the old runbook. The formatter call sites are class C. |
| `tests/test_enforcement_events.py` except the class B and class C rows | They assert `ConsoleHandlers` tallies, the embedded route, and profile-scoped dashboard reads. |
| `tests/test_enforcement_integrity.py` except the class C rows | They drain events through `ConsoleHandlers` and `_enforcement_summary`. Signing itself is class C. Tamper detection on the new reader is `tests/hermes/dashboard/test_activity.py::test_a_signed_event_verifies_and_a_tampered_one_does_not`. |
| `tests/test_pet250_credential_reporting.py` except the spool assertion ported in class C | The assertions on `petasos.console._history` and `_approvals`. |
| `tests/conftest.py::_isolate_enforcement_spool`, `_isolate_history_sink`, `_isolate_reviewed_file` | They import the console to retarget its process-global paths. The history and reviewed files go away with the console. Remaining spool writes pass an explicit path. |
| `tests/test_scanner_bootstrap.py::TestCallerFormatting` | It asserts the log lines of `build_dashboard_pipeline` and the plugin's `_deferred_init`. `build_scanners` itself stays, and the other tests in that file stay. |
| `tests/test_config.py::TestDecodeEncodedPayloads.test_config_meta_help_plain_distinct` | It reads `petasos.console._config_meta._FIELD_META`. The other tests in that class stay. |
| `tests/test_docs_usage_consistency.py::test_docs_config_sections_match_meta`, `test_docs_links_present_in_console_js` | They compare the usage doc to the console catalogue and to the console scripts. The other tests in the file stay. |
| `tests/config/test_legacy_parity.py::test_three_presets_migrate_without_overrides`, `test_console_probe_base_severity_matches_the_console` | The first reads the strength-dial registry. The second fires `petasos.selfmod.console_probe`, which existed only for a console 401. The rest of the file stays. |
| `tests/test_spec_audit_coverage.py` | It calls `petasos.console.server._extract_field_from_error`. |
| `tests/enforce_parity/plugin_adapter.py`, and `record.py`'s ability to regenerate `outcomes.json` from the plugin | The record stays. Replay against the enforcer and the Hermes adapter stays. |

## B4c — the flat config, the bridge, the profiles, and the old builder

Class A tests only the deleted code. Class B is live behaviour an existing
tree test already pins. Class C was rewritten onto the tree and passes beside
the old modules until those modules go. When a file mixed classes, each test
is named.

### Class A

| Old test | Why it is only the deleted code |
|---|---|
| `tests/config/test_legacy.py` | The bridge: `bind`, profile forms, preserved flat Semgrep fields, the leniencies. |
| `tests/config/test_legacy_parity.py` except `test_selfmod_base_severities_match_the_guard` | Equality of the flat document, the profile JSON, and the strength presets with the tree. |
| `tests/scanners/test_legacy_bootstrap_parity.py` | Registration differences between `build_scanners` and `compose`. |
| `tests/test_config.py` | The flat dataclass: validation, `from_dict`/`to_dict`, secret redaction, bool coercion. Bool rejection and the tier-3 floor are `tests/config/test_schema.py` and `tests/config/test_sections.py`. |
| `tests/test_profiles.py` | `ProfileResolver` loading, merge, register, and serialisation. |
| `tests/test_profiles_retained_ref.py` | A caller cannot mutate a parsed profile through the dict it passed in. The tree stores mappings read-only (`tests/config/test_schema.py`). |
| `tests/test_profiles_suppress.py` except `TestCodeGenerationCommandSuppress` | The profile parser strips unsuppressible rules. The tree rejects them (`tests/config/test_sections.py`, `tests/adversarial/profiles/test_suppress_bypass.py`). |
| `tests/test_scanner_bootstrap.py` | `build_scanners` outcomes and log-free status records. `auto` plus a missing package is `tests/scanners/test_registry.py`. |
| `tests/test_scanner_bootstrap.py::TestPromptGuardUpgradeBehavior` | The old builder registered an absent PromptGuard and then fail mode blocked. `compose` does not register `auto` when the probe says absent. |
| `tests/test_pipeline_health.py::test_list_profiles_names_the_built_ins` | `Pipeline.list_profiles`. The five roles are `tests/config/test_layers.py`. |
| `tests/test_pipeline_health.py::test_flat_reconfigure_keeps_the_secret_and_names_semgrep`, `test_flat_apply_keeps_an_explicit_legacy_on_the_session_objects` | Flat reconfigure preserving Semgrep fields and a session secret on the flat object. A tree reconfigure keeps `Secrets` (`tests/adversarial/config/test_config_poisoning.py::test_pipeline_replace_preserves_session_secret`). |
| `tests/test_pipeline_health.py::test_flat_config_rejects_a_low_tier_a_long_wait_and_a_blank_sink` | Flat validation. The tree rejects the same values in `tests/config/test_sections.py`. |
| `tests/test_hermes_integration_defaults.py::TestConfigFromDictRoundTrip` | Flat `from_dict`: unknown keys dropped, base64 `session_secret`, `detect_rtl_override`. The tree rejects unknown keys. Secrets are bytes beside the config. |
| `tests/config/test_legacy.py::test_tree_route_matches_the_bridge`, `test_guard_tree_route_matches_the_bridge` | The bridge and the tree agree. `tests/parity` is that proof. |
| `tests/test_composition_gate.py`, `scripts/hermes_composition_gate.py`, `scripts/hermes_multiprofile_harness.py` | They import `build_scanners` and the flat `from_dict`. Another task owned them. This change made `mypy --strict .` fail on the script, so they were deleted here. |

### Class B

| Old test | Covering test |
|---|---|
| `tests/test_hermes_smoke.py` was rewritten in place rather than deleted. The import-and-scan path is also `tests/test_pipeline.py`. | `tests/test_pipeline.py` |
| The profile-description essay in `tests/test_pet135_codegen_tuning.py::test_codegen_suppression_set_is_exactly_what_we_decided` | The suppress set, confidence floor, severity override, injection scope, and posture stay on that test, read from the coding role. The long JSON description was the profile file. |
| `tests/test_ingestion_backstop.py` custom profile `tier_thresholds` of 150/300/500 | Roles do not carry tier thresholds. The cap is the tree's tier 1 divided by four (`tests/test_ingestion_backstop.py::test_admin_profile_does_not_lower_the_scan_cap`). |

### Class C

| Old test | New test | What it protects |
|---|---|---|
| `tests/test_selfmod_detection.py` | same file, tree config and `tools.aliases` | A hostile alias does not hide a config write. |
| `tests/test_ingestion_backstop.py` | same file, roles on the guard and tree fields for ttl, audit, and session caps | One scan cannot cross a tier. Admin and research do not change the cap. |
| `tests/test_pet135_codegen_tuning.py` | same file, `resolve({"role": "coding"})` | Routine coding stays clean, inbound injection still blocks, outbound injection does not, and the downgraded ML finding does not reach a blocking tier. |
| `tests/test_profiles_suppress.py::TestCodeGenerationCommandSuppress` | same test, coding and general roles | `curl \| sh` stays a finding. A bare pipe does not, under coding. |
| `tests/adversarial/profiles/test_suppress_bypass.py` register tests | same names, `resolve` | Unknown roles are rejected. Overrides do not replace the built-in role. |
| `tests/adversarial/normalization/test_unicode_bypass.py::test_fold_leet_not_a_detection_control`, `test_detect_rtl_override_inert_end_to_end` | same names, one tree scan | Leet folding and RTL detection still fire. There is no toggle to contrast. |
| `tests/adversarial/config/test_config_poisoning.py::test_pipeline_config_isolation` | same test | The pipeline holds the frozen tree it was given. `reconfigure` replaces it. |
| `tests/config/test_legacy_parity.py::test_selfmod_base_severities_match_the_guard` | `tests/test_selfmod_detection.py::test_selfmod_base_severities_match_the_guard` | A config write is critical and a config mention is high. |
| `tests/config/test_legacy_parity.py` integer `frequency_weights`, `semgrep_enabled: false`, and an explicit null | `tests/config/test_migrate.py` | An integer weight becomes a float. Disabling Semgrep matches the default. A null is carried into overrides. |
| `tests/config/test_legacy_parity.py` unknown `entities_extra` | `tests/config/test_sections.py::test_invalid_document_names_the_path` | An unknown extra entity names `scanners.presidio.entities_extra`. |
| `tests/config/test_legacy.py` hash mode without a key | `tests/config/test_secrets.py::test_hash_mode_without_a_key_is_rejected_where_config_meets_secrets` | The pipeline and `reconfigure` still reject hash mode when `Secrets` has no key. |
| `tests/test_hermes_integration_defaults.py` live cases | same file, tree plus `Secrets` | An exempt tool can be allowed while its parameters are unsafe. A session secret requires `host_id`. |
| `tests/test_benchmarks.py` scanner construction | `compose` | The benchmark still measures the composed stack. |
| `tests/test_scanner_composition.py::test_real_scanners_reach_plugin_decisions` | same test, `Enforcer` | The four real-scanner decisions, for general and coding. Not run: the weights are not on disk. |
| `tests/test_pipeline_health.py::test_a_classifier_error_does_not_raise` | new, from the flat apply test | A self-modification classifier error is recorded as no match. |

## Kept, and edited only where a deleted path is named

| File | Edit |
|---|---|
| `tests/test_architecture.py` | Drop the console from the import-direction allowlist. The direction check stays. |
| `tests/test_scanner_bootstrap_structure.py` | Drop the reference plugin, `verify.py`, and `petasos/console/_standalone.py` from the allowlist and the bootstrap pair. `Pipeline.__init__` and `petasos/pipeline/ingest.py` stay. |
| `tests/test_ingestion_backstop.py` | Delete the three plugin-driven tests named in class B, and the plugin importer. The guard and frequency tests stay. |
| `tests/test_scanner_composition.py` | Rewrite `test_real_scanners_reach_plugin_decisions` onto `Enforcer`. The other two tests stay. |
| `tests/test_audit_finding_sink.py` | Deleted. The live lines are the class C port. The module import of the plugin would fail collection. |
| `tests/test_benchmarks.py` | The ingestion benchmarks stop importing the plugin and call `Enforcer.tool_result`. The other benchmarks do not import it. |
| `tests/test_pet135_codegen_tuning.py` | A comment names the plugin file. Left until the comment sweep, unless a collection or lint rule requires the edit. It does not import the plugin. |
| `tests/parity/corpus.json` | Not edited. Some cases quote `petasos.console` and name old test files as their source. Changing the text would move the verdict oracle. |

## D1: source-text checks

Tests follow the package layout. These implementation-shape checks are replaced
by the named behaviour checks; structural rules remain in `tests/test_architecture.py`.

| Old test id | Why retired | Covering behaviour |
|---|---|---|
| `tests/enforce/test_formatter_sites.py::test_every_block_site_calls_a_formatter` | A literal count of formatter calls constrained implementation, not block or notice behaviour. | `tests/enforce/test_messages.py`; `tests/enforce/test_decisions.py::test_guard_denial_covers_tier3_and_tier2`; `tests/enforce/test_decisions.py::test_ingestion_annotation_paths`; `tests/enforce/test_fallback.py::test_read_only_is_skipped_and_a_finding_blocks`; `tests/enforce_parity/test_enforce_parity.py::test_enforcer_matches_record` |
| `tests/test_version_sourcing.py::test_no_hardcoded_version_literal_in_the_hermes_adapter` | Grepping version literals is replaced by checking generated version and dependency values after changing the package version. | `tests/hermes/test_manifest.py::test_generated_versions_and_wheel_range_follow_the_package`; `tests/test_init.py::test_package_version_single_source` |
| `tests/test_param_scan_structure.py::test_fallback_uses_the_shared_helper_and_no_json_dumps` | Call counts, constant names and cap-comparison locations constrain implementation rather than parameter scanning. | `tests/enforce/test_param_scan.py::test_warm_and_fallback_scan_identical_text_outbound`; `tests/guard/test_params.py::test_render_keeps_raw_strings_serializes_values_and_drops_none`; `tests/guard/test_params.py::test_render_caps_characters_at_the_shared_ceiling` |
| `tests/test_param_scan_structure.py::test_fallback_direction_is_the_shared_constant` | Call counts, constant names and cap-comparison locations constrain implementation rather than parameter scanning. | `tests/enforce/test_param_scan.py::test_warm_and_fallback_scan_identical_text_outbound`; `tests/guard/test_params.py::test_render_keeps_raw_strings_serializes_values_and_drops_none`; `tests/guard/test_params.py::test_render_caps_characters_at_the_shared_ceiling` |
| `tests/test_param_scan_structure.py::test_scan_params_uses_the_shared_helper_and_no_inline_serialization` | Call counts, constant names and cap-comparison locations constrain implementation rather than parameter scanning. | `tests/enforce/test_param_scan.py::test_warm_and_fallback_scan_identical_text_outbound`; `tests/guard/test_params.py::test_render_keeps_raw_strings_serializes_values_and_drops_none`; `tests/guard/test_params.py::test_render_caps_characters_at_the_shared_ceiling` |
| `tests/test_param_scan_structure.py::test_scan_params_direction_is_the_shared_constant` | Call counts, constant names and cap-comparison locations constrain implementation rather than parameter scanning. | `tests/enforce/test_param_scan.py::test_warm_and_fallback_scan_identical_text_outbound`; `tests/guard/test_params.py::test_render_keeps_raw_strings_serializes_values_and_drops_none`; `tests/guard/test_params.py::test_render_caps_characters_at_the_shared_ceiling` |
| `tests/test_param_scan_structure.py::test_scan_params_holds_no_cap_comparison` | Call counts, constant names and cap-comparison locations constrain implementation rather than parameter scanning. | `tests/enforce/test_param_scan.py::test_warm_and_fallback_scan_identical_text_outbound`; `tests/guard/test_params.py::test_render_keeps_raw_strings_serializes_values_and_drops_none`; `tests/guard/test_params.py::test_render_caps_characters_at_the_shared_ceiling` |
| `tests/test_param_scan_structure.py::test_the_cap_is_compared_in_exactly_one_place_and_it_is_the_helper` | Call counts, constant names and cap-comparison locations constrain implementation rather than parameter scanning. | `tests/enforce/test_param_scan.py::test_warm_and_fallback_scan_identical_text_outbound`; `tests/guard/test_params.py::test_render_keeps_raw_strings_serializes_values_and_drops_none`; `tests/guard/test_params.py::test_render_caps_characters_at_the_shared_ceiling` |
| `tests/test_scanner_bootstrap_structure.py::test_both_bootstraps_route_through_helper` | The old console and reference-plugin bootstraps are gone; the live route loop is empty and the synthetic route tests exercise only that retired checker. | `tests/scanners/test_registry.py::test_one_composition_covers_registered_and_quiet_states`; `tests/test_architecture.py::test_no_unallowlisted_scanner_construction` |
| `tests/test_scanner_bootstrap_structure.py::test_retro_pre_fix_plugin_would_be_flagged` | The old console and reference-plugin bootstraps are gone; the live route loop is empty and the synthetic route tests exercise only that retired checker. | `tests/scanners/test_registry.py::test_one_composition_covers_registered_and_quiet_states`; `tests/test_architecture.py::test_no_unallowlisted_scanner_construction` |
| `tests/test_scanner_bootstrap_structure.py::test_retro_pre_fix_console_would_be_flagged` | The old console and reference-plugin bootstraps are gone; the live route loop is empty and the synthetic route tests exercise only that retired checker. | `tests/scanners/test_registry.py::test_one_composition_covers_registered_and_quiet_states`; `tests/test_architecture.py::test_no_unallowlisted_scanner_construction` |
| `tests/test_scanner_bootstrap_structure.py::test_missing_bootstrap_file_is_a_violation` | The old console and reference-plugin bootstraps are gone; the live route loop is empty and the synthetic route tests exercise only that retired checker. | `tests/scanners/test_registry.py::test_one_composition_covers_registered_and_quiet_states`; `tests/test_architecture.py::test_no_unallowlisted_scanner_construction` |
| `tests/test_scanner_bootstrap_structure.py::test_renamed_bootstrap_function_is_a_violation` | The old console and reference-plugin bootstraps are gone; the live route loop is empty and the synthetic route tests exercise only that retired checker. | `tests/scanners/test_registry.py::test_one_composition_covers_registered_and_quiet_states`; `tests/test_architecture.py::test_no_unallowlisted_scanner_construction` |
| `tests/test_selfmod_floor_shape.py::TestRecordSelfmodShape::test_single_is_enabled_gate` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/pipeline/test_selfmod_recording.py::test_selfmod_alerts_with_other_features_off_and_audit_follows_its_switch` |
| `tests/test_selfmod_floor_shape.py::TestRecordSelfmodShape::test_is_enabled_audit_only` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/pipeline/test_selfmod_recording.py::test_selfmod_alerts_with_other_features_off_and_audit_follows_its_switch` |
| `tests/test_selfmod_floor_shape.py::TestGuardSelfmodWeightShape::test_uses_requires_token` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/guard/test_selfmod_tokens.py::test_selfmod_updates_a_tracker_without_the_frequency_feature` |
| `tests/test_selfmod_floor_shape.py::TestGuardSelfmodWeightShape::test_no_session_secret_if` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/guard/test_selfmod_tokens.py::test_selfmod_updates_a_tracker_without_the_frequency_feature` |
| `tests/test_selfmod_floor_shape.py::TestEvaluateSelfmodShape::test_contains_critical_literal` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/session/test_alerting_selfmod.py::test_selfmod_alerts_keep_severity_and_bypass_cooldown` |
| `tests/test_selfmod_floor_shape.py::TestEvaluateSelfmodShape::test_no_rule_cooldowns_access` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/session/test_alerting_selfmod.py::test_selfmod_alerts_keep_severity_and_bypass_cooldown` |
| `tests/test_selfmod_floor_shape.py::TestFrequencyFloorLiterals::test_config_write_floor` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/session/test_frequency_selfmod.py::test_selfmod_weight_floors_override_zero_weights` |
| `tests/test_selfmod_floor_shape.py::TestFrequencyFloorLiterals::test_config_ref_floor` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/session/test_frequency_selfmod.py::test_selfmod_weight_floors_override_zero_weights` |
| `tests/test_selfmod_floor_shape.py::TestNoSelfmodConfigField::test_no_selfmod_in_config` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/config/test_selfmod_controls.py::test_schema_exposes_no_selfmod_disable_control` |
| `tests/test_selfmod_floor_shape.py::TestNoSelfmodConfigField::test_no_selfmod_field_in_the_config_tree` | AST names, literals and gates are replaced by public API outcomes; the old config __init__ scan was also vacuous after the package move. | `tests/config/test_selfmod_controls.py::test_schema_exposes_no_selfmod_disable_control` |

One check in that list was kept, in `tests/test_architecture.py`:
`test_the_plugin_directory_holds_no_sample_attack`. It reads shipped files,
but their text is what Hermes's install-time scan judges, and the tests that
run the real scan are skipped in the default run.
