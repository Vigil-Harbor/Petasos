# Hermes host facts

Checked against upstream Hermes Agent tag `v0.23.1`, commit
`3b421578588243f920886e6fe79a6faa87ea026e` (the annotated tag object is
`b65acf3fdc1d43bd889211ea8e37032974b395a5`). The checkout is a depth-1 clone.
`running_hermes_version()` reports `0.23.1` even though `pyproject.toml` says
`0.0.0`; version info is taken from the git tag.

Sandbox: `/tmp/petasos-hermes-host.vRnSPr` (about 1.3 GB when this was
written: checkout 405 MB, the `uv sync` virtualenv 123 MB, and
`HERMES_HOME` 810 MB after package-manager environment generations).
`HOME` is `<sandbox>/home`. `HERMES_HOME` is `<sandbox>/hermes_home`.
Every Hermes command went through `<sandbox>/bin/with-sandbox`, which sets
both and drops inherited `HERMES_*` variables. `get_hermes_home()` returned
the sandbox. `account_default_hermes_home()` still computes
`/Users/<user>/.hermes` from the account password entry
(`hermes_constants.py` lines 72–96). Nothing in this pass called that path.

Section 7 of `docs/architecture/redesign.md` was updated after section 9
below. The corrections in sections 1–8 are from the first sandbox pass and
were not rewritten.

## What section 7 should change

1. An approve directive is not granted because `approvals.mode` is
   `"approve"`. That string is not a mode. It is normalised to `manual`,
   and `manual` fail-closes when no human is attached. The default mode is
   `smart`, and `smart` fail-closes the same way. Auto-grant happens for
   `approvals.mode: off`, for `HERMES_YOLO_MODE`, for
   `approvals.single_query_mode` / `cron_mode` / `unattended_mode` set to
   `approve` while that context is actually active, and for a
   `command_allowlist` entry `plugin_rule:<rule_key>`. Upstream does not
   ship a researcher profile whose mode is approve.
2. `type: secret` does not make `ctx.set_config` write `.env`, and
   `ctx.get_config` does not read `.env`. The form writer refuses a secret
   in `config.yaml`. The env name is the manifest's `env:` or else
   `<PLUGIN_ID>_<KEY>` upper-snake. A new process does not copy `.env` into
   `os.environ` just by loading plugins; `hermes_cli.config.get_env_value`
   reads the file.
3. `hermes plugins install` does not accept a local directory. A filesystem
   path is parsed as GitHub `owner/repo`. A git URL and a `#subdir` (or
   `.git/<subdir>`) install. Index requirements in `pyproject.toml` are
   installed into a package-manager generation under
   `<HERMES_HOME>/installs/.../environments/<id>/venv`, and the running
   process does not switch to it. A direct URL requirement (a local wheel
   or a git URL) is not managed. Copying the directory into
   `<HERMES_HOME>/plugins/<id>/` and installing the wheel into the
   interpreter that is actually running Hermes loads and validates. That
   install is not a package-manager declaration, so a later generation
   need not keep it.
4. The hook timeout defaults to 30 seconds and is
   `plugins.hook_callback_timeout`. After a `pre_tool_call` timeout the
   callback is suppressed for 60 seconds and later calls fail closed
   immediately. A block directive with no message is ignored. A callback
   exception becomes a block whose text names the callback. Two
   `transform_tool_result` strings: the first in registration order wins.
   `{"action": "modify", "args": {...}}` is a third `pre_tool_call`
   result. `pre_approval_request` does not run when the no-human gate
   fail-closes.
5. `hermes plugins validate` requires `name`, `version`, and `description`.
   If `register()` registers hooks, `provides_hooks` must list them or
   validation fails. The loader also accepts the legacy `hooks:` key;
   validate does not. A one-line `from <wheel> import register` stays
   `kind: standalone`. The kind scanner reads `__init__.py` text, and the
   substring `MemoryProvider` there marks the plugin `exclusive`, which
   keeps it out of the general loader.
6. Settings live in that profile's `config.yaml`. A sticky `active_profile`
   retargets the CLI when `HERMES_HOME` is the profile root. `ctx.get_config`
   sees a disk write on the next call. `${NAME}` expands on read and the
   file keeps the literal. The schema `default` is what the settings form
   displays. `ctx.get_config` of an unset key returns the caller's default.

## 1. Directory plugin in front of a wheel

**Statement.** Hermes discovers, validates, enables, and loads a directory
whose `__init__.py` is `from standin_hostfacts.plugin import register`,
once that wheel is on the interpreter. `plugin.yaml` must have `name`,
`version`, and `description`. Validation also requires `provides_hooks` to
match what `register()` registers. The one-line import does not change
kind.

**Ran.** Built `standin_hostfacts-0.1.0` with `uv build` and a plugin
directory with `plugin.yaml`, the one-line `__init__.py`, and a
`pyproject.toml` whose `dependencies` is empty.

- `hermes plugins validate` on a directory whose `register` is a local
  no-op passes with only `name`, `version`, and `description`.
- The same command fails, exit 1, when `description` is missing:
  `plugin.yaml missing required field(s): description`.
- A `config_schema` type `choice` fails validation. The accepted types
  are `array`, `bool`, `boolean`, `dict`, `float`, `int`, `integer`,
  `list`, `number`, `object`, `secret`, `str`, `string`. A schema with a
  bool, two string fields that carry `choices` or `enum`, a dict, and two
  secrets passes ("shape valid").
- Before the wheel is installed, validate fails the capability probe:
  `import failed: No module named 'standin_hostfacts'`. The manifest
  fields and the schema still pass. After `uv pip install` of the wheel
  into the sandbox interpreter, validate passes, including "register() ran
  in isolation" and "declared hooks matches registrations".
- A manifest that uses `hooks:` instead of `provides_hooks` is loaded by
  the parser as those hooks (`plugins_manifest.py` line 577) and fails
  validate: `undeclared hooks registered (not in provides_hooks):
  pre_tool_call`.
- Copied the directory to `<HERMES_HOME>/plugins/standin-hostfacts/` and
  listed it in `plugins.enabled`. `discover_and_load()` loaded it
  `enabled`, `error` null, `kind` `standalone`, with all eight hooks
  registered. The same for a second directory, `standin-b`, sharing the
  wheel.
- `parse_manifest_file` on the one-line `__init__.py` returns kind
  `standalone`. The same function on an `__init__.py` that also contains
  the text `MemoryProvider` returns kind `exclusive`.

**Source.** Required validate fields: `hermes_cli/plugin_validate.py`
lines 101–113. Hook declaration check: lines 435–457. Kind scan of
`__init__.py` only: `hermes_cli/plugins_manifest.py` `_detect_kind_from_source`
lines 287–298 and `_manifest_kind` lines 529–548. User plugins are opt-in
via `plugins.enabled`: `hermes_cli/plugins_discovery.py` lines 122–130 and
`collect_directory_manifests` lines 210–212.

**For section 7.** The directory shape works. The generated `plugin.yaml`
has to include `provides_hooks` for every hook `register()` registers, or
`hermes plugins validate` fails. The legacy `hooks:` spelling in the
reference plugin is not enough for validate. The one-line import is safe.
The kind scanner must not be fed an `__init__.py` that mentions
`MemoryProvider`, `CronScheduler`, `ComputerUseProvider`, or
`register_provider` together with `ProviderProfile`, or the plugin is
treated as `exclusive` and the general loader does not run it.

## 2. Install route

**Statement.** `hermes plugins install` accepts a catalog name, a git URL,
and `owner/repo` with an optional subdirectory (`#subdir` or a path after
`.git/`). It does not accept a local directory. Index dependencies in the
plugin `pyproject.toml` are prepared into a package-manager environment
generation, and the running interpreter does not switch. A direct URL
dependency is dropped. Installing the wheel into the current interpreter
and copying the directory is what actually loaded the plugin here.

**Ran.**

- `hermes plugins install <absolute directory> --no-enable` exited 1. The
  path was rewritten to
  `https://github.com/tmp/petasos-hermes-host.vRnSPr.git` with a
  subdirectory, then clone failed. Identifier parsing is
  `hermes_cli/plugins_cmd.py` `_resolve_git_url` lines 301–337: a value
  that is not `https://`, `http://`, `git@`, `ssh://`, or `file://` and
  contains slashes becomes GitHub `owner/repo`.
- `hermes plugins install file://<local git repo> --no-deps` exited 0 and
  cloned the repo root into `<HERMES_HOME>/plugins/`. The root has no
  `plugin.yaml`, so Hermes warned that it may not be a plugin and left it
  disabled.
- `hermes plugins install file://<repo>#plugins/standin-hostfacts
  --no-deps` exited 0 and installed that subdirectory at
  `<HERMES_HOME>/plugins/standin-hostfacts`, disabled because `--no-deps`
  skips enable.
- The `.git/<subdir>` form is parsed. A second install of the same plugin
  exited 1 with "already exists" rather than "invalid identifier".
- A `pyproject.toml` dependency
  `standin-hostfacts @ file://<wheel>` validates with a warning and zero
  managed requirements: `direct URL requirement(s) are not managed by PM`.
  `pm/plugin_declarations.py` `applicable_requirements` lines 98–109 drops
  any requirement that has a URL.
- `hermes plugins install file://<repo>#deps-probe --yes-deps --enable`,
  with `dependencies = ["tabulate==0.9.0"]`, exited 0, printed the
  dependency, and enabled the plugin. `tabulate` landed in
  `<HERMES_HOME>/installs/680c3055b60c7ed0/environments/43595faffa4948dd8b89f6e22563bea4/venv/`.
  The sandbox interpreter that was running the CLI raised
  `ModuleNotFoundError` for `tabulate`. Hermes printed: "A running process
  never switches dependency environments; restart Hermes (hermes gateway
  restart for the gateway) to load them." That restart was not run.
- `hermes pm install standin-hostfacts` exited 1. `hermes pm install`
  takes managed tool names from the lock, not an arbitrary package. The
  docs say the same thing (`website/docs/developer-guide/plugins/index.md`
  around the "Distribute via pip" section).
- `uv pip install` of the local wheel into the sandbox venv, then copying
  the directory and setting `plugins.enabled`, is the path that
  `discover_and_load` and a later `hermes plugins validate` both accepted.
  Upstream documents that pip installs are not durable package-manager
  declarations (`index.md` lines 1383–1386 in this tag).

**For section 7.** The open install question in 7.6 resolves as follows.
`hermes plugins install` from a git URL that points at the plugin
directory does install index requirements named in `pyproject.toml`, into
the package-manager generation, and the process that ran the command does
not import them until a later process uses that generation. It will not
install a wheel that is only a path or a git URL. `petasos hermes install`
that writes the directory and puts the wheel on the interpreter Hermes is
running works against this checkout. A later `hermes plugins enable` that
builds a new generation will not keep that wheel unless the requirement is
an index package the generation solves. `hermes pm install` is not a way
to add the wheel.

## 3. Settings

**Statement.** `config_schema` with a bool, two choice fields, a dict, and
two secrets validates. Non-secret values land in
`plugins.entries.<id>.settings` in that profile's `config.yaml`.
`ctx.get_config` reads that tree, returns the caller's default when the
key was never set, and expands `${NAME}` on read. A write from another
process is visible on the next `get_config` in an already-running process.
Secrets are a different store.

**Ran.** Schema as in section 1. `plugin_settings_fields` reported
`enabled` boolean, `role` and `level` enums (from `choices` and from
`enum`), `overrides` json, `session_secret` secret with env
`PETASOS_SESSION_SECRET`, and `hash_key` secret with env
`STANDIN_HOSTFACTS_HASH_KEY`. Before any write, the form's `value` for
`enabled` was the schema default `true`, while `ctx.get_config("enabled",
"SENTINEL")` returned `SENTINEL`. `ctx.get_config("does_not_exist")`
returned `None`. `ctx.get_config("does_not_exist", "SENTINEL")` returned
`SENTINEL`.

`ctx.set_config` wrote `enabled`, `role`, `level`, and
`overrides: {nested: {k: 1}, flag: true}` under
`plugins.entries.standin-hostfacts.settings`.
`ctx.get_config("overrides")` returned that dict.
`ctx.get_config("overrides.nested.k")` returned `1`. A later
`set_config("overrides", {"nested": {"k": 1}})` kept `flag` and a key
written after that (`a`). `save_plugin_setting` calls `save_config` with
`merge_existing=True` (`plugins_state.py` lines 83–90), and that merge
keeps sibling keys already stored under a dict setting. A dotted write
`overrides.probe` sets that leaf. It does not clear the rest of
`overrides`.

`save_plugin_settings` (the writer the Desktop form uses) rejected
`role: "nope"` with `must be one of the declared choices`, rejected
`hash_key` with `is a secret; it is stored in .env, not config.yaml`, and
accepted `enabled: true` plus an overrides dict. `ctx.set_config` does not
apply that choice check: it stored `role: ${STANDIN_TOKEN}`.

`ctx.set_config("session_secret", "sandbox-secret-value")` wrote the
string into `config.yaml` and left `.env` empty.
`save_env_value("PETASOS_HASH_KEY", ...)` wrote `.env`. In that process
`get_env_value` and `os.environ` both saw it, because `save_env_value`
publishes into the process (`config.py` lines 2688–2713). A new process
had `os.environ` absent for that name, `get_env_value` returned the file
value, and `ctx.get_config("hash_key", "SENTINEL")` stayed `SENTINEL`,
including after `discover_and_load()`.

`ctx.get_config("role")` with the file containing `${STANDIN_TOKEN}`
returned `expanded-from-env`, then `expanded-second` after the variable
changed, with no restart. The file still had the literal.

Another process called `save_plugin_setting` for `level`. The already
imported process's next `ctx.get_config("level")` returned the new value
as soon as that process had exited. `hermes config set
plugins.entries.standin-hostfacts.settings.level relaxed` printed the
sandbox config path and the same process's next `get_config` returned
`relaxed`.

A profile directory `<HERMES_HOME>/profiles/alpha/config.yaml` holding
`role: from-alpha` was read by a process whose `HERMES_HOME` was that
directory. With `HERMES_HOME` still the root and `active_profile`
containing `alpha`, `hermes config get
plugins.entries.standin-hostfacts.settings.role` printed `from-alpha`.
The already-running process, which had not gone through
`hermes_cli.main`, kept reading the root.

**Source.** `ctx.get_config` / `set_config`: `hermes_cli/plugins_context.py`
lines 73–87. `set_config` calls `save_plugin_setting`, which writes
`plugins.entries.<id>.settings` (`plugins_state.py` lines 66–90). Form
writer and secret env names: `plugins_settings.py` lines 70–76 and
128–149. Expansion: `config.py` `_expand_env_vars` lines 1405–1477.
`load_config_readonly` is cached on the file signature (lines 1985–1989),
so the next call after a write re-reads. CLI profile retarget when
`HERMES_HOME` is the root: `hermes_cli/main.py` `_apply_profile_override`
lines 508–571. Profile name from the home path: `profiles.py`
`get_active_profile_name` lines 1979–1993.

**For section 7.** Per-profile storage and "schema default is display
only" hold. "Nothing but Hermes writes `config.yaml`" matches
`ctx.set_config` and `hermes config set`, which share that writer. A
plain change on disk is visible to the next `get_config` in a process
that is already up; there is no timer and no restart. `${NAME}` does
expand, so a doctor check for that sequence is aimed at a real read.
The secret paragraph needs to change. Declaring `type: secret` does not
place the value in `.env`. The form path refuses to put it in
`config.yaml` and names an env var. `ctx.set_config` puts it in
`config.yaml` and `ctx.get_config` will then return it. A plugin that
only reads `ctx.get_config` will not see a secret that exists only in
`.env`. The env name is `PETASOS_SESSION_SECRET` only when the manifest
sets `env:` or the derived `<id>_<key>` happens to spell that. For plugin
id `petasos` and key `hash_key` with no `env:`, the derived name is
`PETASOS_HASH_KEY`. Whether a Desktop form reaches a running gateway
without a restart was not run: no gateway was started. The in-process
read path does see the write immediately.

## 4. Hook contracts

**Statement.** The eight hooks exist and the real dispatchers call them
with the keyword arguments below. `pre_tool_call` fail-closes on a block
with a message, on an exception, and on timeout. It proceeds on `None`,
on a block with no message, and on an unrecognised action. `approve` is
section 5. `transform_tool_result` keeps the original string on `None` or
on an exception, and uses the first string in registration order when
several plugins return strings.

**Ran.** Both stand-in plugins registered all eight hooks. Callbacks
recorded kwargs. Dispatch used Hermes's functions, not a reimplementation:
`_dispatch_pre_tool_call_hooks`, `_apply_transform_tool_result_hook`,
`_emit_post_tool_call_hook`, `lifecycle.invoke_hook` with the production
payloads, and `_fire_approval_hook`.

`pre_tool_call` kwargs: `tool_name`, `args`, `task_id`, `session_id`,
`tool_call_id`, `turn_id`, `api_request_id`, `middleware_trace`,
`conversation_id`, `telemetry_schema_version`.

| Return | Host decision |
|---|---|
| `{"action": "block", "message": "stopped by stand-in"}` | block text is that message |
| `{"action": "block"}` | proceed (`block` is `None`) |
| `None` | proceed |
| `{"action": "dance", "message": "nope"}` | proceed |
| `{"action": "modify", "args": {"path": "rewritten.txt"}}` | proceed, `modified` is `{"path": "rewritten.txt"}` |
| raise `RuntimeError("boom")` | block `pre_tool_call plugin callback on_pre_tool_call raised RuntimeError: boom` |

`plugins.hook_callback_timeout` was set to `0.25` (the default in code is
30). A callback that slept 2 seconds produced, after 0.309 seconds, the
block `pre_tool_call plugin callback timed out or is still running`. The
log line was `timed out after 0.25s — skipping`. The next call, with a
different `tool_call_id`, returned the same block in 0.001 seconds and
logged `skipped after previous timeout or while still running`.

`transform_tool_result` kwargs add `result`, `duration_ms`, `status`,
`error_type`, `error_message` and omit `middleware_trace`. A string return
replaced the result. `None` left `original-result`. A raise left
`original-result` and logged the exception at warning. With standin-b
returning `"from-b"` and standin-hostfacts returning `"from-a"`, the host
result was `"from-b"`. The log order was standin-b then
standin-hostfacts. Independent plugins are registered in alphabetical key
order (`plugins_manifest.py` lines 280–283, `ready = sorted(...)`).

`post_tool_call` kwargs are the transform set plus `middleware_trace`.
`_emit_post_tool_call_hook` discards callback returns. The callback ran.

`on_session_start` kwargs from the production call:
`session_id`, `model`, `platform`, `telemetry_schema_version`
(`agent/conversation_loop.py` lines 933–936). Returns are collected by
`invoke_hook` and ignored by that call site.

`subagent_start` kwargs (`tools/delegate_tool.py` lines 369–374):
`parent_session_id`, `parent_turn_id`, `parent_subagent_id`,
`child_session_id`, `child_subagent_id`, `child_role`, `child_goal`,
plus `telemetry_schema_version`.

`subagent_stop` kwargs (`tools/delegate_tool_results.py` lines 381–388):
`parent_session_id`, `parent_turn_id`, `child_session_id`, `child_role`,
`child_summary`, `child_status`, `tool_call_history`, `duration_ms`,
plus `telemetry_schema_version`. This hook is on the caller thread
(`plugins_dispatch.py` line 62), so it is not under the callback timeout.

`pre_approval_request` kwargs: `command`, `description`, `pattern_key`,
`pattern_keys`, `session_key`, `surface`, `turn_id`, `tool_call_id`,
`telemetry_schema_version`. `post_approval_response` adds `choice`.
`_fire_approval_hook` drops the callback return (`approval_context.py`
lines 54–73). A callback that returned a block dict did not change that.

**Source.** Timeout sets and the fail-closed message:
`hermes_cli/plugins_dispatch.py` lines 42–67 and 181–184. Directive
parsing, including "block needs a message" and `modify`:
`hermes_cli/plugins.py` lines 1116–1168. Transform first-string and
fail-open: `model_tools.py` lines 873–890. Valid hook names:
`hermes_cli/plugins.py` lines 111–151.

**For section 7.** The table's failure column holds for `pre_tool_call`
(exception and timeout block) and for `transform_tool_result` (the
original string is kept). It should also say: the timeout is
`plugins.hook_callback_timeout`, default 30, and a timed-out
`pre_tool_call` callback stays suppressed for 60 seconds
(`_HOOK_TIMEOUT_SUPPRESSION_SECONDS`); a block without a message is not a
block; the first transform string in registration order wins; `modify`
exists; observer hooks ignore their returns. `post_tool_call`,
`on_session_start`, and the sub-agent hooks ran and their returns were
not applied. Sub-agent hooks exist in this build.

## 5. Approve

**Statement.** With no human attached, an approve directive from
`pre_tool_call` is blocked, including under the default mode `smart` and
under the string `"approve"`. It is granted for `approvals.mode: off`,
for yolo, for the three context modes when that context is active and the
mode is `approve`, and when `command_allowlist` already contains
`plugin_rule:<rule_key>`.

**Ran.** Each case was a fresh process. The callback returned
`{"action": "approve", "message": "please confirm", "rule_key": "demo-rule"}`.
`_dispatch_pre_tool_call_hooks` was the entry. No approval callback was
installed, and `HERMES_INTERACTIVE` / `HERMES_GATEWAY_SESSION` were unset,
so nothing waited on a prompt.

| Config / context | Normalised `approvals.mode` | Result |
|---|---|---|
| no approvals block (default) | `smart` | blocked, no interactive user or gateway |
| `mode: manual` | `manual` | same block |
| `mode: smart` | `smart` | same block |
| `mode: approve` | `manual` | same block |
| `mode: off` | `off` | proceed |
| `HERMES_YOLO_MODE=1` before import | (yolo active) | proceed |
| `single_query_mode: approve` and `HERMES_SINGLE_QUERY_SESSION=1` | `smart` | proceed |
| `single_query_mode: deny` and that env | `smart` | blocked, text names `approvals.single_query_mode: approve` |
| `cron_mode: approve` and `HERMES_CRON_SESSION=1` | `smart` | proceed |
| `cron_mode: deny` and that env | `smart` | blocked, text names `approvals.cron_mode: approve` |
| `unattended_mode: approve` and `HERMES_SESSION_PLATFORM=api_server` | `smart` | proceed |
| `unattended_mode: deny` and platform `webhook` | `smart` | blocked, text names `approvals.unattended_mode: approve` |
| `command_allowlist` contains `plugin_rule:demo-rule`, mode `manual` | `manual` | proceed |

The no-human block was
`BLOCKED: Tool 'read_file' requires approval (please confirm) but no interactive user or gateway is present to approve it. A plugin flagged this action for human confirmation.`
On that path the only hook that ran was `pre_tool_call`.
`pre_approval_request` and `post_approval_response` did not.

**Source.** Default mode `smart`, and `cron_mode` / `single_query_mode` /
`unattended_mode` default `deny`: `hermes_cli/config_defaults.py` lines
1646–1662. Unknown `approvals.mode` becomes `manual`:
`tools/approval_context.py` lines 264–280. `_VALID_MODES` is `manual`,
`smart`, `off` (line 263). Plugin approve calls `_run_approval_gate` with
`fail_closed_when_no_human=True`: `tools/approval.py` lines 1246–1271.
The no-human branch is lines 1116–1152. `mode: off` and yolo return
approved at line 1110. Permanent allowlist short-circuit is lines
1112–1114, and the key is `plugin_rule:<rule_key>` (lines 1262–1264).
Yolo is frozen from `HERMES_YOLO_MODE` at import (`approval.py` line 48).

**For section 7.** Replace the sentence that an approval mode of
`approve` grants the directive, including for the researcher. Upstream
has no such mode and no built-in researcher profile. `HostInfo` should
report the mode that is actually in effect (`manual` / `smart` / `off`),
whether yolo is on, and whether this process is in a single-query, cron,
or unattended context whose matching mode is `approve`. `dangerous_posture:
approve` does not mean allow under `smart` or `manual` when nobody is
attached. It means allow when `approvals.mode` is `off`, when yolo is on,
when the active unattended context's mode is `approve`, or when the rule
key is already on `command_allowlist`. The deny messages tell the model
the config key that would allow the action. Approval observers do not see
the fail-closed no-human decision.

## 6. What the plugin can learn about its host

**Statement.** From the process that is running the callback, the plugin
can read the Hermes home, a profile name derived from that home, the
Hermes version, whether sub-agent hooks are in this build, the approvals
block, yolo, and whether a `plugin_rule:` key is on the permanent
allowlist. There is no separate "auto-approve is on" flag.

**Ran.** Inside the sandbox process, after plugins had loaded:
`get_hermes_home()` was `<sandbox>/hermes_home`.
`get_active_profile_name()` and `current_profile_name()` were `default`
for that root. For `<root>/profiles/alpha` the CLI resolved the profile
name `alpha` (section 3). `running_hermes_version()` was `0.23.1`.
`subagent_start` and `subagent_stop` are in `VALID_HOOKS` and
`has_hook` was true once the stand-in had registered them.
`tools.approval.is_approved("", "plugin_rule:demo-rule")` was false
before the allowlist write and the gate then granted that key (section 5).
`_get_approval_mode()` returned the normalised mode in each case.
`_yolo_active()` was true only in the process started with
`HERMES_YOLO_MODE=1`.

**Source.** Home: `hermes_constants.py` `get_hermes_home` lines 194–201.
Profile name: `profiles.py` lines 1979–2014. `current_profile_name` also
reads `HERMES_PROFILE_NAME` / `HERMES_PROFILE` when no context override is
set. Version: `plugins_manifest.py` `running_hermes_version` lines
461–465. Allowlist: `tools/approval.py` `is_approved` line 448 and
`_read_permanent_allowlist` lines 492–512 (`command_allowlist` on the
loaded config).

**For section 7.** `HostInfo` can be filled without a private API: home
and profile from `hermes_constants` / `hermes_cli.profiles`, version from
`running_hermes_version()`, sub-agent support from `"subagent_start" in
VALID_HOOKS` (registration is not the same as the host emitting them;
this build's delegate tool does emit them, section 4). "Auto-approve" is
the combination in section 5, not one config key. "Always approved" for a
Petasos rule is `plugin_rule:<rule_key>` on `command_allowlist`.

## 7. Self-protection surface

**Statement.** These are the switches that stopped or would stop the
stand-in from enforcing. Paths are under the profile's `HERMES_HOME`.

**Ran.**

- `hermes plugins disable standin-b` exited 0. It printed
  `Plugin standin-b disabled` and `No running gateway answered` plus the
  line `hermes gateway restart`. During that state `plugins.enabled` was
  `["standin-hostfacts"]` and `plugins.disabled` was `["standin-b"]`.
  `hermes plugins enable standin-b` put it back on `enabled` and cleared
  `disabled`. The same pair worked for `standin-hostfacts`.
- `hermes plugins remove standin-remove` exited 0 and deleted
  `<HERMES_HOME>/plugins/standin-remove`. The printed path was the
  plugins directory.
- A fresh process with `HERMES_SAFE_MODE=1` discovered no user plugins
  (`discover_and_load` returned before the scan).
- A fresh process with only `HERMES_IGNORE_USER_CONFIG=1` still loaded
  both user plugins. Plugin discovery reads `load_config()`, which does
  not consult that variable. `load_cli_config` does (`cli_config_load.py`
  lines 256–270), and `--safe-mode` sets both variables
  (`hermes_cli/main.py` `_apply_safe_mode` lines 2842–2847).

**Source.** Safe-mode skip: `hermes_cli/plugins.py` lines 413–416.
`plugins.disabled` wins over `plugins.enabled`, including when a name is
on both lists: `plugins_discovery.py` `gate_manifest` lines 269–298.
Disable implementation: `plugins_cmd.py` `cmd_disable` lines 783–796.
Remove: `plugins_cmd_remove.py` `cmd_remove` lines 104–118. The flag
`--safe-mode` is defined in `hermes_cli/_parser.py` (the inherited
`--safe-mode` store_true). `plugins.hook_callback_timeout` is the other
config key that changes hook behaviour (section 4). Setting it to `0`
disables the timeout thread and runs the callback inline
(`plugins_dispatch.py` `_hook_uses_callback_timeout`, lines 204–208);
that was read in source and not given its own run.

**For section 7.** A guard that watches commands and paths has to
recognise at least:

- command `hermes plugins disable <id>` and `hermes plugins enable <id>`
- command `hermes plugins remove <id>`
- directory `<HERMES_HOME>/plugins/<id>/` (`plugin.yaml`, `__init__.py`,
  and the rest of the tree)
- `plugins.enabled` and `plugins.disabled` in `<HERMES_HOME>/config.yaml`
  (a name on both is disabled)
- `plugins.entries.<id>` in that file, including `settings`
- `plugins.hook_callback_timeout` in that file
- `<HERMES_HOME>/active_profile` (the CLI follows it when `HERMES_HOME`
  is the root)
- environment `HERMES_SAFE_MODE=1` and the command flag `--safe-mode`
- the follow-up command the disable output prints, `hermes gateway restart`

`HERMES_IGNORE_USER_CONFIG` / `--ignore-user-config` alone did not stop
discovery. `plugins.entries.<id>.settings.enabled` is the Petasos boolean
inside the settings tree. Hermes's own on/off switch is the enabled and
disabled lists, plus safe mode.

## 8. Section 7 corrections and the documented way

The corrections are the list at the top. Two further gaps:

- Section 7.6 asks whether settings written through the Desktop form reach
  a running gateway without a restart. No gateway was started. The
  in-process `get_config` path sees `hermes config set` and
  `save_plugin_setting` on the next call. A gateway is a separate process
  with its own cache; this pass does not say when that process re-reads.
- Section 7.6's kanban sentence, that a worker reads settings frozen at
  session creation, was not run. A search of `hermes_cli/kanban*.py` did
  not show a snapshot of `plugins.entries`. It stays open. Starting a
  kanban worker was out of scope: it is a long-running process and can
  call a model.

Upstream's documented shape for what Petasos is doing is a directory
plugin with `plugin.yaml` (`provides_hooks`, `config_schema`) and
`register(ctx)`, dependencies declared as index requirements in
`pyproject.toml`, installed with `hermes plugins install` / `enable` so
the package manager admits them
(`website/docs/developer-guide/plugins/index.md`, "Python dependencies"
and "Distribute via pip"). Section 7's directory-in-front-of-a-wheel
matches that shape. The part it cannot follow, confirmed here, is a wheel
that is not an index package: direct URLs are unmanaged, and a pip
install into the current environment is explicitly called out as not
durable. `config_schema` types and the Desktop form are the documented
settings surface; `ctx.get_config` on each call matches the docs and the
code. The docs also say `provides_hooks` is what validate checks, which
section 7's sample manifest does not list.

## 9. Registration, profiles in one process, context lifetime

Checked in the same checkout. This pass used sandbox
`/tmp/petasos-hermes-c2a-reg` (`HOME` `<sandbox>/home`, `HERMES_HOME`
`<sandbox>/hermes_home`, every command through `bin/with-sandbox`). The
probe was one sandbox process:
`/tmp/petasos-c2a-reg-probe.py` through `bin/with-sandbox`, against the
adapter before the registration change. A later test,
`tests/hermes_host/test_petasos.py::test_reload_and_a_second_profile_keep_enforcement`,
repeats the same Hermes calls against the fixed adapter.

**When `register` runs again.**

- A second `discover_and_load()` with no `force` did not call `register`.
  Source: `PluginManager.discover_and_load` returns when `_discovered` is
  set and `force` is false (`hermes_cli/plugins.py`, the early return inside
  the discovery lock).
- `discover_and_load(force=True)` called `register` again, on the same
  manager object, with a new context. Before the fix the module flag skipped
  binding. The manager's `pre_tool_call` list for Petasos went from 1
  callback to 0. A `write_file` of `ignore previous instructions` was blocked
  before the reload and was not blocked after (`block` was null). The
  enforcer object and its core were the same object, and `session_tier` was
  still `none`, but Hermes's dispatcher no longer called it. Source:
  `discover_and_load` calls `unload()` then `_discover_and_load_inner`
  (`hermes_cli/plugins.py`). `unload` with no plugin argument disposes every
  ledger registration (`hermes_cli/plugins_ledger.py` `unload` /
  `_unload_scoped`). The load calls `register_fn(ctx)`
  (`hermes_cli/plugins_loader.py` `_load_plugin_scoped`). Callers of the
  forced path include `discover_plugins(force=True)` and the gateway
  `reload-plugins` verb (`gateway/run_plugin_rewire.py` `reload_plugins_verb`).
- Calling `register` a second time on a new `PluginContext` for that same
  manager, without an unload, did not add a callback. The list stayed at 1.
  That was the flag refusing to bind, which is also why the reload above
  bound nothing.
- `hermes plugins validate` calls `register` in a child process
  (`hermes_cli/plugin_validate.py`, the capability probe). It does not share
  this process's module state.

**Profiles in one process.**

One process can serve more than one profile. `get_plugin_manager` caches a
`PluginManager` per resolved home (`_plugin_managers_by_home` in
`hermes_cli/plugins.py`). The comment there says a process switches profiles
with `set_hermes_home_override`, and that plugins capture the home at
registration. `set_hermes_home_override` is a `ContextVar`; it does not
change `os.environ` (`hermes_constants.py`). `get_hermes_home` prefers that
override (`hermes_constants.py`). User plugins are read from
`get_hermes_home() / "plugins"` (`hermes_cli/plugins_discovery.py`
`collect_directory_manifests`).

Ran: wrote `<HERMES_HOME>/profiles/alpha` with its own `config.yaml`
(`enabled: false`, `role: coding`) and a copy of the plugin directory, then
`set_hermes_home_override` to that directory and `discover_and_load` on the
manager `get_plugin_manager` returned. It was a different manager. `register`
ran. Before the fix it bound 0 hooks, the enforcer object was the root's,
and the injection was not blocked. `ctx.profile_name` was `alpha`
(`PluginContext.profile_name` calls `get_active_profile_name`,
`hermes_cli/profiles.py`). `ctx.get_config("enabled")` was false and
`ctx.get_config("role")` was `coding`. The context kept from the root load
returned those same alpha values while the override was set, and the
sentinel again when it was not: `get_config` reads
`load_config_readonly()` (`hermes_cli/plugins_context.py`), and that reads
`get_config_path()` which is `get_hermes_home() / "config.yaml"`
(`hermes_cli/config.py`). Dispatch uses the same home:
`_dispatch_pre_tool_call_hooks` calls `hermes_cli.lifecycle.invoke_hook`,
which calls `plugins.invoke_hook`, which uses `_delivery_manager` →
`get_plugin_manager` (`hermes_cli/plugins.py`).

There is no plugin-facing profile-change hook. A search of this checkout
found no `on_profile_change`. The first load logged
`Plugin 'petasos' registered unknown hook 'on_profile_change'`. The hook is
not in `VALID_HOOKS` (`hermes_cli/plugins.py`). Nothing fires it.

**Context lifetime.**

The context from the first load was still callable after
`discover_and_load(force=True)`. Its `_manager` was the same object. `get_config`
still answered. It is safe to keep and to call from a hook for the active
home, because the read follows the active home rather than a home stored on
the context. It is not safe to treat it as the home from `register` time if
the override has since moved.

## 10. Dashboard `--isolated`, plugin environments, and a missing plugin API

Checked in sandbox `/tmp/petasos-p1a-host` (Hermes v0.23.1, commit
`3b421578588243f920886e6fe79a6faa87ea026e`). Node 26.12.1 and pnpm 12.15.0
were installed under that sandbox and `pnpm --dir web run build` wrote
`hermes_cli/web_dist/`. Every command went through `bin/with-sandbox`.

**What `--isolated` does.** It does not change which Python imports a
plugin and it does not change `plugins.isolation`. On `hermes dashboard`
and `hermes serve` it opts out of two routing steps. Without it, a second
dashboard on a machine that already has one attaches to that server and
exits (`hermes_cli/main_dashboard.py` `_attach_to_host_backend`, the
`isolated` return near the start of the function). A launch whose active
profile is not `default` or `custom` re-execs as `-p default` and
preselects the named profile (`_route_named_profile_dashboard`);
`--isolated` returns before that re-exec. The flag's help text is
`hermes_cli/subcommands/dashboard.py` (`--isolated`). On the default
profile, with no dashboard already listening, the flag changes nothing
about plugin loading.

**Plugin isolation.** `plugins.isolation` is `in_process` or `host`
(`hermes_cli/plugin_isolation.py` `isolation_mode`). The default is
`in_process`: user plugin code, including a dashboard API module, is
imported into the Hermes process. `host` keeps third-party code in a
plugin-host process; the dashboard then forwards `/api/plugins/<name>/`
(`hermes_cli/web_server_dashboard.py` `_mount_hosted_plugin_api`) and logs
`Mounted plugin API routes via the plugin host`. The homes in this pass
had no `plugins.isolation` key, so the mode was `in_process`. The 404
below is not host mode.

**The per-request gate.** Every `/api/plugins/<name>/` request is checked
again after mount (`_plugin_api_request_refused`,
`_plugin_route_secret_scope`). The check re-reads `plugins.enabled` and
`plugins.disabled` for the profile the request acts for. A withheld plugin
raises HTTP 404 with detail `Plugin not found`. That is not the body the
failing call returned.

**Where a 404 `{"detail": "Not Found"}` comes from.** If the plugin's API
was not mounted, the request hits `_PluginApiHotMount`. That tries
`_try_hot_mount_plugin_api` and, on failure, returns
`JSONResponse({"detail": "Not Found"}, status_code=404)`. Mount imports
the plugin's `api` file (`_mount_one_plugin_api` →
`plugin_isolation.import_user_code`). An exception is logged and the mount
returns false, so the route is never added. `has_api` on
`/api/dashboard/plugins` is only "the manifest's `api` path is a file
inside the plugin's `dashboard/` directory" (`_dashboard_plugin_entry`).
It does not import that file. An unauthenticated `/api/` call is refused
with 401 `{"detail": "Unauthorized"}` by `auth_middleware` in
`hermes_cli/web_server.py` before routing, so a 401 does not show that the
route exists. The dashboard process's own stdout does not include the
mount failure. That line is in `<HERMES_HOME>/logs/agent.log` and
`gui.log`.

**Two Pythons.** `hermes` imports `hermes_bootstrap` before anything else
(`hermes_cli/main.py`). Bootstrap calls `pm.environments.activate_dependencies`,
which removes every `site-packages` entry from `sys.path` and adds the
committed environment from `<HERMES_HOME>/installs/<key>/facts.json`.
With no committed environment, a virtualenv keeps the packages it started
with. `python -m petasos` and a harness run under the sandbox interpreter
do not import `hermes_bootstrap`, so they keep the sandbox virtualenv.

**What commits the environment.** Enabling a plugin goes through
`plugins_cmd._activate_key` → `_set_plugin_enabled` →
`plugins_admission.admit_plugin_set_change` → `pm.client.sync_venv`.
`petasos hermes install` calls Hermes's
`dashboard_set_agent_plugin_enabled`, which is that path. The committed
environment is a new virtualenv. It does not contain a wheel that was
only `pip install`ed into the sandbox interpreter.

**Ran.** On a fresh sandbox, `pytest tests/hermes_host` was 3 failed, 26
passed, in 105 seconds. The three failures were
`GET /api/plugins/petasos/status` with the dashboard session token:
`404 {"detail": "Not Found"}`. The unauthenticated call was 401 and
`/api/dashboard/plugins` listed Petasos with `has_api: true`. Pytest ran
`test_cli.py` first. After only
`test_install_then_doctor_reports_protected`, `<HERMES_HOME>/installs/.../facts.json`
existed and its environment had no `petasos` distribution. Importing
`hermes_cli.main` left `sys.path` with that environment's `site-packages`
and not the sandbox virtualenv's. While Petasos was an editable install,
`_editable_impl_petasos.pth` had already pushed the worktree onto
`sys.path`; activation removes entries named `site-packages` and leaves
that path, so `import petasos` still worked. The dashboard fixture then
installed the wheel with `uv pip install --reinstall`, which removed the
`.pth`. The dashboard process logged `Failed to load plugin petasos API
routes: No module named 'petasos'` at `import_user_code` and the
authenticated call returned the hot-mount 404. The same 404 remained for a
later dashboard run on that home, because the committed environment stayed.

**A real user can hit this.** `petasos hermes install` (and
`hermes plugins enable petasos`) commits a dependency environment that
does not include a wheel installed only into the interpreter that ran the
command. The next `hermes dashboard` activates that environment, cannot
import `petasos`, and does not mount `/api/plugins/petasos/`. The tab is
still listed. The API answers 404 once the caller is authenticated, and
the dashboard's stdout does not say why. An editable install hides it
until something replaces that install with a wheel. The development
install's own text warns that a later Hermes update can build such an
environment; the enable inside that same command builds one immediately.
This pass did not change package code.

## 11. Getting Petasos into the committed environment

Checked in sandbox `/tmp/petasos-p2-env`, a copy of `/tmp/petasos-p1a-host`
(Hermes v0.23.1, the same commit). The copy's editable finder and script
shebangs were retargeted at the copy before any further command. Every
command went through `bin/with-sandbox`. Homes were fresh directories under
`<sandbox>/homes/`.

**The defect, on the code before the fix.** `petasos hermes install` wrote
the plugin directory with `dependencies = []` and turned the plugin on
through `dashboard_set_agent_plugin_enabled`. That calls
`admit_plugin_set_change` → `pm.client.sync_venv`, which commits
`<home>/installs/<key>/environments/<id>/venv`. The generation's package
list had no `petasos`. Doctor, running in the interpreter that had the
wheel, printed `Protected` and exited 0. A new process that imports
`hermes_cli.main` (which imports `hermes_bootstrap`, which calls
`activate_dependencies`) had `sys.path` pointing at that generation's
`site-packages` and raised `ModuleNotFoundError: No module named 'petasos'`.
`discover_and_load` recorded the plugin with error `No module named
'petasos'`. `hermes petasos doctor` exited 2 with `hermes: 'petasos' is not
a hermes command.` The plugin never registered the `petasos` subcommand,
because it never imported.

**What Hermes installs.** `pm/plugin_declarations.py` `applicable_requirements`
keeps index requirements and drops any requirement with a URL, including a
direct wheel URL. A plugin whose `dependencies` is empty is not a workspace
member (`installs_packages` is false) and does not enter the environment
stamp. A non-empty index requirement does. `pm/workspace.py`
`_workspace_member` copies the plugin tree into the generation and keeps
`[tool.uv.sources]` path entries: an absolute path is left as written, a
relative path inside the plugin directory is copied with the tree. A path
source for a direct dependency is installed. A path source for a
*transitive* dependency of that package is not; those resolve from the
index (`UV_FIND_LINKS` / `UV_INDEX_URL` / the bridged pip index, see
`pm/index_config.py` `bridged_index_settings`).

**Ran.** A plugin `pyproject.toml` with `dependencies = ["petasos==0.4.0"]`
and `petasos = { path = "wheels/petasos-0.4.0-py3-none-any.whl" }`, then
`dashboard_set_agent_plugin_enabled("petasos", enabled=True)`. The generation
log contained `petasos==0.4.0 (from file://…/plugin-sources/…/wheels/…)`. A
new process imported `petasos` from that generation's `site-packages`.
Changing the requirement to `petasos[probe]==0.4.0`, where the wheel's
`probe` extra depends on `probe-pkg==0.0.1`, and calling
`_admit_and_save_plugin_sets` with the current enabled set (the plugin was
already enabled, so `plugins enable` would have been a no-op:
`_activate_key` returns false without syncing) failed until
`UV_FIND_LINKS` pointed at a directory containing `probe-pkg`. With that
set, the rebuild installed `probe-pkg` and a new process imported it.
`_admit_and_save_plugin_sets` is the same admission `enable` uses. It does
not require the enabled set to change. A refusal leaves the previous
environment in place (`AdmissionRefused`).

**The public index already has 0.4.0.** `https://pypi.org/pypi/petasos/json`
reports version `0.4.0`, and that release's metadata is the older package
(it requires `pyjwt` and does not ship this tree's `petasos.hermes`). An
index requirement `petasos>=0.4,<0.5` is satisfied by that release. The
development route therefore pins `petasos==<this version>` to a path source
inside the plugin directory, so a later rebuild cannot substitute the index
package. The released route is the index requirement, and it installs
whatever the configured index resolves.

**What rebuilds the environment.** Enabling or disabling a plugin goes
through `_activate_key` → `_admit_and_save_plugin_sets` → `sync_venv` when
the set actually changes. `hermes plugins install` with `--enable` does the
same at the end of `cmd_install`. `hermes plugins update` republishes
through the update transaction. A Hermes self-update syncs when the venv
drifts: `hermes_cli/post_update.py` `step_provision_runtimes` calls
`pm.sync_venv(explicit=True, evict_incompatible_plugins=True)` for the
`venv` package, and `hermes_cli/update_completion.py` calls `sync_venv` on
the first-generation selection. This pass did not run a Hermes update. The
stamp (`pm/packages.py` `expected_stamp` plus `pm/workspace.py`
`members_stamp`) hashes the plugin tree, so a changed wheel or a changed
extra is a new generation. A plugin with `dependencies = []` and no
build-system is not a member and does not by itself force a new generation.

**Extras.** A requirement may name an extra: `petasos[prompt-guard]==0.4.0`.
`applicable_requirements` keeps it (it has no URL). uv installs the extra's
dependencies from the index. `uv sync --extra` on the workspace is a
different mechanism: it installs extras of the workspace members that are
named on the sync command, which is how Hermes selects its own extras, not
how a plugin dependency's extras are selected. Putting the extra on the
petasos requirement is what reaches the environment.

**Index order, checked with uv 0.13.5 (the uv this Hermes pins).** An extra
index is searched before the default index, and the default strategy is
`first-index`: the first index that publishes a name supplies it. A private
index set as `UV_EXTRA_INDEX_URL`, with PyPI left as the default, supplied
`six` 9.9.9 from the private index and `packaging` from PyPI. A 404 from the
extra index falls through. The reverse (`UV_INDEX_URL` private,
`UV_EXTRA_INDEX_URL` PyPI) takes a package PyPI publishes from PyPI, which
is how an earlier attempt installed the public `petasos` 0.4.0 instead of
this tree's wheel. `UV_FIND_LINKS` adds locations but does not beat a newer
version on an index that is searched as well.

**Ran after the fix, on isolated homes.** `petasos hermes install` (the
development route) left a new process importing `petasos` from the committed
`site-packages`, with the plugin loaded and a `write_file` of
`ignore previous instructions` blocked. Deleting that package while the
plugin files stayed put made `petasos doctor` print `Not protected` and name
`petasos hermes install`. That second run restored the package.
`sync_venv(explicit=True, repair=True)` is what restores it.
`sync_venv(..., repair=True, plugins=Selection(...))` is refused:
`repair restores the recorded environment; it cannot change features or plugins`
(`pm/install.py`). Enabling a second plugin that depends on another wheel
rebuilt the environment and the development wheel was still imported.
`petasos scanner add prompt_guard`, with stub `torch` and `transformers`
wheels on a private extra index, put those stubs in the next process;
`petasos scanner remove prompt_guard` took `torch` out. `hermes plugins
install file://<repo>#hermes-plugin/petasos --enable --yes-deps`, with this
tree's wheel on that same kind of extra index, imported `petasos.hermes` from
the committed environment and blocked the same injection. The dashboard API
answered after `petasos hermes install` with no separate wheel install into
the committed environment.

## 12. Command gate and plugin hooks

Ran later, against the same tag, in a copy of a prepared sandbox. The full
record is `docs/architecture/hermes-command-overlap.md`. The order tests
are `tests/hermes_host/test_command_gate_order.py`.

`pre_tool_call` runs before the terminal command gate and before the
`execute_code` script gate. A plugin block skips both gates. A plugin
approve plus a command Hermes would also ask about is two prompts. With
`approvals.mode: off`, a plugin block still stops the command before the
gate, and a hook cannot block once the gate has approved, because
`post_tool_call` runs after execution. A headless process whose mode is
`manual` approves a non-hardline dangerous command and still blocks
`rm -rf /`. `write_file` does not enter the command gate.

## 13. Machine-level pinning

Read from Hermes `v0.23.1`; **run in S1b on 2026-11-11**, only inside
`/tmp/petasos-s1b-sbx`. Managed directories, profile homes, and the inactive
machine-location stand-in were all in that sandbox. No administrator command
or real machine-level file was used. The platform locations are source-checked;
Windows was not run. Evidence: `tests/hermes_host/test_pin.py` and `pin_harness.py`.

**What can be pinned.** `managed_config_keys` flattens a nonempty mapping to
dotted names; a list, scalar, null, **or empty mapping** is one leaf
(`hermes_cli/managed_scope.py`, `_flatten_keys`). An empty mapping is marked
managed, despite being a mapping. `apply_managed_overlay` deep-merges managed
values on top of the profile after expanding `${VAR}` in the managed document
through Hermes's environment-reference reader. Existing ordinary scalar and list leaves
win. `hermes config set` refuses exact managed keys; bulk saves strip managed
leaves instead of saving them. Parent-group writes need not be refused, but
the overlay still fixes the ordinary pinned leaves.

**The important exceptions, confirmed by hand edits.** A managed mapping,
including `{}`, retains profile-only children. New entries can therefore be
added to `rules.severity_overrides`, `tools.aliases`, and `frequency.weights`.
Some API saves strip the whole empty/null managed group, so the API child write
has no effect; a hand edit survives. A managed `null` also does not replace a
profile mapping: `_deep_merge` explicitly ignores null over a dict. The default
unset fields affected are `scanners.presidio.entities`,
`scanners.semgrep.engine_path`, `scanners.semgrep.engine_sha256`, and
`frequency.weights`. Their hand-written mappings are visible to `ctx.get_config`.
Petasos may reject that type, but a pin cannot claim to hold the raw value.
The original source-reading statement that *any* leaf wins was too broad.
Hermes also retains unresolved `${VAR}` / `${env:VAR}` placeholders. Petasos
refuses those in a pin snapshot; the sandbox confirmed that an already expanded
value stays fixed after its environment variable changes, and an unresolved
reference writes no managed document.

**Plugin enablement and settings, run.** Both `plugins.enabled` and
`plugins.disabled` are lists and pinned as whole values. The actual
`hermes plugins disable petasos` command rewrites the profile; a new process
still loads Petasos from the managed lists. No plugin can be added to or
removed from those lists with an effective profile write. Safe mode can still
skip loading plugins. `PluginContext.get_config` uses `load_config_readonly`,
which sees the managed overlay. `save_plugin_setting` refuses an exact managed
path with `PermissionError`. A previously absent sibling remains writable when
only the stored overrides were pinned: the sandbox wrote `tools.enabled` beside
pinned `tools.self_change`. A complete resolved leaf tree fixes this omission
for the ordinary fixed leaves, subject to the mapping/null exceptions above.
The plugin API, `hermes config set`'s implementation, Petasos's settings form,
and `petasos config set` were tried against all 80 setting paths. Unpin restored
unmanaged API writes and retained an unrelated managed key.

**Scope and location.** This file is **global to every profile/process using
that managed directory**. It has no profile selector. `get_managed_dir` uses a
nonempty `$HERMES_MANAGED_DIR`, otherwise the POSIX default `/etc/hermes`.
**If the override does not exist, the result is None; it does not fall back
to `/etc/hermes`.** The earlier description of fallback was wrong. Under pytest
the default is ignored unless an override is set. The source's single default
is `/etc/hermes` even on macOS; there is no native macOS or Windows location
and no `ProgramData` path. Petasos uses the POSIX default on macOS/Linux,
offers no default Windows location, and can use an explicitly provisioned
override. Administrator ownership was not exercised; expected deployment modes
remain directory `0755`, file `0644`, owned by the administrator. A writable
file or replaceable file in a writable directory is not protection from this
account.

**Redirect, run.** The wrapper drops inherited `HERMES_*`, so the harness sets
`HERMES_MANAGED_DIR` inside its sandbox process. It is never persisted to an env
file. Redirecting to a second sandbox directory stops the original overlay.
With `_DEFAULT_MANAGED_DIR` replaced on the **calling managed-scope module** by
a sandbox stand-in, the doctor detects Petasos keys in the unused machine file
and fails with “Pin not in force.” A user who controls the process environment
can bypass a real machine pin in this way too.

**Hook timeout, run.** Hermes's `_resolve_hook_callback_timeout` uses 30 seconds
by default, defaults negatives/invalid input, caps at 600, and preserves zero.
Zero disables the worker timeout and runs callbacks inline, rather than
switching callbacks off. Petasos pins the effective value returned by this
helper. Real tests covered zero, negative, and above-cap input, a later hand
edit, and a refused `hermes config set`. The pre-tool hook timeout is fail-open,
so this setting belongs in the pin; pinning it does not repair Hermes's timeout
behavior or silently choose a different time limit.

## 14. Commands that change a guardrail

Read from the Hermes `v0.23.1` tree in the sandbox copy
`/tmp/petasos-s1a-sbx` (the same tag as the sections above). Nothing was
run. Line numbers are the parser or the function that performs the write.

**Plugins** (`hermes_cli/subcommands/plugins.py`). These change which
plugins are installed, enabled, or disabled, or replace a plugin's files:

| Command | Lines | When it is a change |
|---|---|---|
| `plugins install` | 18–48 | The identifier is `petasos`, ends with `#petasos` or `/petasos`, or names every plugin (`--all`, `-a`, `all`, `*`). `file:///tmp/other#petasos` is this case. |
| `plugins update` | 68–78 | A name of `petasos` or a source for it, or no name at all. With no name the help says it offers every plugin that has an update. |
| `plugins remove`, `rm`, `uninstall` | 131–133 | The name is `petasos` or every plugin. |
| `plugins enable` | 147–156 | Same. |
| `plugins disable` | 158–160 | Same. The parser has no `--all` flag; a word `--all` or `-a` is still treated as every plugin. |
| `plugins auto-update` / `autoupdate` | 80–88 | The next word is `on` or `off`. That sets `plugins.auto_apply`, which applies later plugin updates with nobody present. With no word it only shows the setting. |
| `plugins adopt` | 90–99 | The name is `petasos`. It writes provenance so a later `update` can replace that plugin's files. |
| `plugins trust-update-url` | 101–111 | The name is `petasos`. It is the only command that changes the saved update URL. |
| `plugins pack install` | 187–191 | Always. The pack is a set of installs and its contents are not in the command. `pack show` and `pack export` only read. |

Not a change: `list` / `ls` (135), `search` (50), `browse` (57), `show` (205),
`doctor` (171), `capabilities` (162), `check-updates` / `check` (113, "NEVER
mutates"), and `validate` (59). `validate --install-deps` (62–66) installs
the plugin under test's declared dependencies into the current venv for a
probe. It does not enable a plugin or replace Petasos's files, so it is not
matched.

**Configuration** (`hermes_cli/subcommands/config.py`). `set` and `unset`
(27–37) on `plugins.enabled`, `plugins.disabled`, `plugins.hook_callback_timeout`,
`plugins.entries.petasos`, and `plugins.auto_apply`. `edit` (18) opens the
config file in an editor, so it can change any of those keys. `migrate` (42)
writes new options into the file. `show`, `get`, `path`, `env-path`, and
`check` only read.

**Active profile.** `set_active_profile` (`hermes_cli/profiles.py` 1956–1968)
writes or removes `active_profile`. `hermes profile use` always calls it
(`hermes_cli/profile_cmd.py` 151–158). `profile delete` (profiles.py
1792–1793) and `profile rename` (2304–2305) retarget the pointer when it
names that profile; both are treated as a change because the command can do
so. `profile update --force-config` (subcommands/profile.py 147–157)
overwrites that profile's `config.yaml`. `profile list`, `show`, `create`,
`install`, `export`, and `update` without `--force-config` do not write the
pointer. `--profile` and `-p` (`hermes_cli/_parser.py` 13–16) are consumed
before argparse and point the process at another home.

**Safe mode.** `--safe-mode` (`_parser.py` 210–211) disables plugins for
that process. `_apply_safe_mode` (`main.py` 2842–2847) sets
`HERMES_SAFE_MODE`, `HERMES_IGNORE_USER_CONFIG`, and `HERMES_IGNORE_RULES`.
`--ignore-user-config` (`_parser.py` 206–207) ignores `config.yaml`, which
is where the enabled-plugin list lives. `HERMES_IGNORE_USER_CONFIG` is the
environment form (`gateway_chat.py` 42).

**Restart or reload.** `gateway restart` (subcommands/gateway.py 164),
`gateway start` (151), and `gateway run --replace` (83–87, replaces the
running instance). `hermes update` (subcommands/update.py) replaces the
install and restarts gateways unless `--no-gateway-restart` (111–114); a
restart is the normal end of the command, so the command is a change.
`--check` (19), `--plan` (22), `--list-venv-holders` (28), and
`--install-id` (91) are read-only and are not. `gateway stop` (159) stops
the service and does not reload it. `gateway status` and `gateway run`
without `--replace` do not either.

**Home variables.** A prefix assignment of `HERMES_HOME` or
`HERMES_MANAGED_DIR` on a `hermes` command, and `export` of either name,
are a change. `get_managed_dir` (`hermes_cli/managed_scope.py` 45–59) uses
`HERMES_MANAGED_DIR` when it is set. Assigning `HERMES_HOME` on a command
that is not `hermes`, and is not an export, is not.

## 15. What counts as yolo, and what the ask predicate reads

Read from the Hermes `v0.23.1` tree in the sandbox copy, and pinned by
`tests/hermes_host/test_command_will_be_asked.py`. Nothing in that test is
executed. The command strings are arguments.

`_yolo_active` (`tools/approval.py`) is true when `HERMES_YOLO_MODE` was set
at import, when the current session's yolo flag is on, or when
`gateway.session_finite.unattended_turn()` is true. That third source is
`hermes -z`: a finite turn marked unattended. It is not cron, single-query,
or a platform `unattended_mode`. The command gate treats it as yolo, so a
dangerous pattern is approved with no prompt. The study's yolo row is the
session flag. This is the extra source. The session flag is checked against
`get_current_session_key(default="")`, not the `"default"` fallback.

`_get_approval_mode` lives on `tools.approval_context`, not on
`tools.approval`. The gate calls it as `approval_context._get_approval_mode`.

The predicate Petasos calls is `command_will_be_asked` in
`petasos/hermes/host.py`. It calls `detect_dangerous_command` and then the
gate's own helpers for the container skip, the hardline floor, the approval
mode, yolo, the permanent allowlist, `_presence`, and an earlier session
answer. A hardline match is a refusal, not a prompt, so the predicate is
false there even when the detector also flags the command. Where the live
gate prompts in `manual` mode, the predicate is true. Where the gate
approves without asking, it is false. In `smart` mode it is always false:
`_human_decision` calls `_smart_gate` first, and an `approve` verdict from
the guardian model returns approved with no prompt. A plugin's approve
request does not take that path. `request_tool_approval` calls
`_run_approval_gate`, which calls `_human_decision` without `smart`, so it
always reaches a person. Where `detect_dangerous_command` is missing or raises, it is
false while the gate, which bound the function at import, can still prompt.

## 16. Named profiles under one root share an environment

Checked 2026-11-11 in sandbox `/tmp/petasos-u3-sbx`, home
`homes/soak-rehearsal`, with two profiles made by `hermes profile create`
(`ops` and `worker`).

- **One environment for the root.** `hermes plugins enable petasos` run
  for `ops` (`HERMES_HOME=<root>/profiles/ops`, with or without
  `--profile ops`) committed its environment under `<root>/installs/`.
  `<root>/profiles/ops/installs` was not created. Source:
  `pm/environments.py` `dependency_home_root`, and `pm/plugins_state.py`,
  whose first line is "Read every profile's enabled plugins in config
  order for the shared union".
- **The plugin stays per profile.** After the enable, `plugins.enabled`
  changed only in the `ops` config. In `worker`, `hermes plugins list` did
  not list Petasos and `hermes petasos` was not a command. The `petasos`
  package is importable from every profile's new processes, because the
  environment is shared, and is loaded only where the plugin is enabled.
- **Consequence.** Turning Petasos on for one profile rebuilds the Python
  environment every profile under that root starts with next.
- **A Python without Hermes can do half the install.** `petasos hermes
  install --home <root> --profile ops`, run from a Python that cannot
  import Hermes, wrote the plugin files and the wheel and did not turn the
  plugin on. `HERMES_HOME=<root>/profiles/ops hermes plugins enable
  petasos` then built the environment with that wheel, and `hermes petasos
  doctor` reported Protected. A Hermes started by its own launcher runs a
  store Python with `-I`, so there is no "same Python" for a person to
  install Petasos into; this two-step route is the development install
  there.
- **Rollback.** `hermes plugins disable petasos` moved the id to
  `plugins.disabled`, rebuilt the environment, and removed the `hermes
  petasos` command. The `plugins.entries.petasos` settings stayed.

## 17. Seen on a live install, 2026-11-12 and 2026-11-13

These come from installing Petasos into one profile of a real Hermes
`v0.23.1`, started by launchd from a source checkout through Hermes's own
launcher. Each was reproduced or read back afterwards.

- **A `manifest.json` beside the checkout stops every environment rebuild.**
  `pm/runtime.py` `_resident_runtime` reads a `manifest.json` in the
  checkout's parent directory as the mark of a packaged install and then
  wants a `pm-runtime` there. `hermes plugins enable petasos` failed with
  `AdmissionRefused: pm-runtime: packaged PM runtime is missing or invalid —
  reinstall this application`. Nothing was changed by the attempt. An
  unrelated file of that name had been left there. Reproduced in the
  sandbox: with the file, the same refusal; without it, the enable works.
  Ordinary launches were not affected.
- **`hermes gateway restart` rewrites the launchd service definition.** Its
  first output line was "Updated gateway launchd service definition". The
  file it wrote replaced the operator's program arguments with Hermes's
  supervised form (`gateway run --external-supervisor` under an `osascript`
  wrapper), replaced `PATH` with the calling shell's, and dropped the
  operator's lock and state directory settings, although both
  were set in the environment of the command. The restarted gateway then
  kept its locks in Hermes's default lock directory, not the one the
  operator had set. Putting the operator's file back
  and reloading the service with `launchctl bootout` and `launchctl
  bootstrap` restored the earlier behaviour. A clean stop removed the
  gateway's token lock from that directory and left its
  `host-gateway.json` and `host-gateway.lock` there.
- **The command to restart after an enable is Hermes's advice, not ours.**
  `hermes plugins enable` prints `hermes gateway restart`. Petasos does not
  print it. An operator who manages the service definition themselves
  should reload the service their own way.
- **A plugin loaded in the gateway after a service reload.** With the
  operator's definition restored (`gateway run --replace`), the gateway
  started from the new environment and logged Petasos's start-up warning.
  `hermes petasos doctor` reported Protected before and after.

## What was not run

- No Hermes gateway, no messaging platform, no model provider, and no
  model API call.
- No Desktop UI, so the settings form was exercised through
  `plugin_settings_fields` and `save_plugin_settings`, not through a
  window.
- No kanban worker.
- `hermes gateway restart` was printed by disable and by the dependency
  installer and was not executed.
- `account_default_hermes_home()` was evaluated once to see where it
  points. The directory was not opened.

The reusable runner is `tests/hermes_host/`. Its README repeats the safety
rules and the prepare command.
