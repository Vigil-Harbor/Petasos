# Enforcement parity oracle

This directory is a replayable record of what the reference plugin decided.
That plugin is gone, so `outcomes.json` is frozen: nothing in the tree can
regenerate it. Replaying `scenarios.json` through `enforcer_adapter.py` and
`hermes_adapter.py` is how the enforcer and the Hermes hooks are checked
against that record.

`enforcer_adapter.py` replays through `Enforcer` directly.
`hermes_adapter.py` replays through `petasos.hermes.plugin.register` and the
hooks it registers, against a fake Hermes context and a temporary home.
`differences.json` names, on each entry, which of those adapters the
difference applies to. An unlisted difference fails. A listed difference
that does not occur for an adapter it names fails too. The corpus and
`outcomes.json` stay as recorded.

Every scenario runs in its own temporary home. Nothing in the harness reads
or writes a real Hermes home. Scenarios do not share state, so they pass in
any order and in separate processes.

## Scenario

A scenario is host-neutral. It names settings, what the host can do, the
lifecycle it starts in, optional stub scanners, and an ordered list of
steps. Steps are named by what happens (`tool_call`, `tool_result`,
`tool_finished`, `session_start`, `subagent_start`, `subagent_stop`,
`approval_request`, `approval_answer`, `settings`, `arm`, `init_complete`,
`profile_change`, `evaluation_fault`, `open_log_window`), not by a plugin
function.

String values may contain `$home` and `$config`. The adapter substitutes
this run's temporary home and config file, then writes `<home>` and
`<config>` back into the outcome. Compact nodes keep large payloads out of
the file: `{"$repeat": [text, count]}` and `{"$nest": depth}`. A step
`repeat` unrolls into `id-1` .. `id-N` before replay.

Stub scanners are declarative. A rule is "text containing this yields this
finding". `mode: error` fails every scan. `mode: timeout` never returns.
The dev environment has no Presidio or PromptGuard package, but both
wrappers still register and then fail every scan. Scenarios that need the
syntactic ladder set `disabled_scanners` to those two ids. `backends-missing`
leaves them registered and records the result.

## Outcome

Each step is one line in `outcomes.json`. The line carries what an operator
or the model could observe:

- the decision (`allow`, `block`, `approve`, `annotate`, `unchanged`), the
  model-facing message, and for an approval the rule key
- enforcement events written during the step, in order
- `PETASOS_...` log lines, plus the pipeline's `restart required` warnings
- the session tier after the step, when the guard can already report it

`scan_id`, `timestamp` and `sig` are dropped. They are a random id, the
wall clock, and an HMAC under a per-run key. Absolute temporary paths
become `<home>` or `<config>`. Generated `anon-` and `desktop-` session
ids, pids and 64-hex digests are rewritten. A long tool result that is the
original text plus a banner stores the banner and `"body": "input"`.

## The record is frozen

`outcomes.json` was written by replaying the reference plugin. That plugin
has been removed, and `record.py` with it, so the file cannot be regenerated.
A diff in `outcomes.json` is a behaviour change. Do not edit it to make a
failing replay pass. A deliberate change has to be named in `differences.json`
in the same commit, or the record has to be replaced by a new oracle.

## Adding a scenario

Add one object to the `scenarios` list. Give it a new id, a `categories`
list, `settings`, `host`, `lifecycle` (`ready`, `starting`, or
`{"state": "failed", "error": "..."}`), any stub `scanners`, and `steps`.
A new scenario cannot be added to the frozen record. Keep the categories
named in `test_enforce_parity.py` when they cover a situation the list does
not already pin, and explain the new outcome in `differences.json` or replace
the oracle.

## What the plugin adapter reached into

This is how the frozen record was produced. The adapter is gone.

The steps themselves went through the hook callbacks (`_pre_tool_call`,
`_transform_tool_result`, `_post_tool_call`, `_on_session_start`,
`_subagent_start`, `_subagent_stop`, `_pre_approval_request`,
`_post_approval_response`, `_on_profile_change`). Setup that the hooks
cannot express is confined to `plugin_adapter.py`:

- A `starting` or `failed` lifecycle sets `_init_thread_started`,
  `_initialized`, `_init_error`, `_init_done` and `_init_wait_expired`,
  and pins `_session_resolution` plus `_config`. The cold-start budget is
  marked already spent, so a step does not block on the real wait. The
  decision is the one the plugin makes once that wait has returned.
- `init_complete` calls `_deferred_init`, which is the body of the init
  thread.
- Host facts that `register` would have probed (`_approve_directive_available`,
  `_subagent_hooks_available`) are set directly on those two lifecycles.
  A `ready` scenario calls `register` and lets the probe run.
- Stub scanners are appended to `Pipeline._ml_scanners` after init. The
  plugin builds its own scanner list and has no registration seam.
- `evaluation_fault` replaces `ToolCallGuard.evaluate`. A scanner fault
  does not escape `evaluate`, and that is the only way the
  evaluation-failure arm runs. A timeout fault also shortens `_run_async`'s
  15s wait to 0.05s. The exception the hook sees is the same class the
  outer wait raises. The 15s wait has no setting.
- The tier is `_guard._derive_tier`. That is the tier enforcement uses,
  including a parent's tier inherited by a child.
- `open_log_window` calls the plugin's existing clock seams
  (`_reset_disarm_log`, `_reset_ingest_unscanned_log`, `_reset_reload_logs`,
  `_reset_rebind_log`). The windows use `time.monotonic()` and have no
  clock injection.
- After `profile_change`, the adapter submits one `sleep(0)` on the
  plugin's loop. The hook schedules the apply and returns; the yield runs
  after that apply's commit.

The Hermes adapter does not call that hook. Hermes v0.23.1 has no
profile-change event, and the old handler never ran under the host. A
`profile_change` step that carries settings is written onto the active
context, which is how this host exposes the active profile, and `refresh`
applies it on that step. A step that only names a home changes nothing.
- `petasos.hermes.home.hermes_root` is pointed at the temporary home
  for the duration of the scenario. Self-modification discovery otherwise
  lists `~/.hermes`.

## What is not pinned

- A tool-result timeout at the outer budget. That budget is
  `scanner_timeout_seconds + 5`, so it cannot fire without waiting at least
  five seconds. A scanner that exceeds its own timeout returns inside the
  pipeline. With the syntactic floor still healthy, the result is unchanged.
- Fan-out windows expiring. The window is 60s of `time.monotonic()` with
  no seam. Every scenario stays inside one window.
- Frequency half-life decay and alert cooldowns across a long gap. The
  suite does not sleep, so scores do not decay.
- A disarm or reload line appearing because 30s elapsed. The suite opens
  the window through the seams above instead.
- Hook-home mismatch, Hermes profile-pointer resolution, and the capture of
  `HERMES_HOME` from a real process. Those belong to the future host
  adapter. This harness always supplies one temporary home.
