# Guardrail integrity

Status: recognition, approval and refusal are built (S1a, 2026-11-10).
Managed pin commands and the doctor/Overview states are built (S1b, 2026-11-11).
Supersedes the self-protection notes in section 7.4 of `redesign.md`.
The frozen enforcement record is kept; deliberate differences remain in
`tests/enforce_parity/differences.json`.

## Principle

An agent must not be able to switch off, weaken or remove its own guardrails.
A barrier the car can move is not a barrier.

There are two acceptable answers to "can the agent change its own safety
settings at all?", and an operator picks one:

- **With approval.** Yes, but only when the operator has approved that change,
  for that action or for the current session. An approval never stands
  indefinitely.
- **Never.** Changes are an operator action, made outside the agent, by
  someone who has proved they are the operator.

Before the redesign, a write to Petasos settings raised an event and the
session's score, and was allowed while the session was below tier 2.

## What counts as a guardrail

Anything whose change would stop or weaken enforcement, or hide that it
happened:

- Petasos's settings (`plugins.entries.petasos` in the profile's config) and
  its two secrets in the profile's env file.
- Whether the plugin runs: the plugin directory, Hermes's enabled and disabled
  plugin lists, safe mode, the hook timeout, the profile pointer, and the
  commands that change them (`hermes plugins disable|remove|uninstall`,
  `--safe-mode`, `hermes gateway restart`, `hermes config set` on those keys).
  Enabling the plugin with exactly `hermes plugins enable petasos`, as the
  tool call's whole command text, is not a change, unless the same command grants or revokes its tool-override
  permission (`--allow-tool-override`, `--no-allow-tool-override`), which
  Hermes writes into Petasos's entry. Any other `enable` that names the
  plugin or everything (`all`, a version, a source, another plugin beside
  it, `--force`, a global option) is a change.
- The Petasos package itself (uninstalling it, editing its installed files).
- Hermes's permanent approval list where an entry would pre-approve a Petasos
  rule, and Hermes's approval settings (`approvals`).
- The evidence: the event spool and scan history.

Reading settings is not a change. Reading the secrets is a separate concern,
covered by credential protection.

## The setting

One setting, `tools.self_change`, with two values. It is owned by the role
axis, because the right answer depends on who is on the other end of the
conversation.

| Value | Meaning | Default for |
|---|---|---|
| `approve` | The agent may change a guardrail only with a live approval | every role except `support` |
| `never` | The agent can never change a guardrail | `support`, where the person chatting is a customer, not the operator |

### `approve`

A tool call that would change a guardrail is held for approval. The approval
must be fresh and must come from a person:

- **Scope.** "Once" covers that one call. "For this session" covers further
  guardrail changes in the same session until the session ends or
  `tools.self_change_minutes` (default 30) have passed, whichever is first.
  Sessions on a messaging gateway can live for days, so the time limit is what
  keeps a session approval from going stale.
- **No standing approval.** Hermes offers "always", which writes
  `plugin_rule:<rule_key>` into the profile's `command_allowlist`
  (`tools/approval.py` `_persist_choice`, and the short-circuit in
  `_run_approval_gate`). "Session" stores the same key only in that process's
  `_session_approved` for Hermes's current session key. "Once" stores nothing.

  Petasos does not reuse a key. The key is `petasos.guardrail.<generation>.<session>`.
  Each ask takes the next generation, and a generation the host already has on
  its permanent list is skipped. An "always" entry therefore matches no later
  ask and no other session. A "session" or "always" answer is remembered on the
  enforcer's own clock for `tools.self_change_minutes` (default 30, at most
  1440). While that grant is live, later guardrail changes in the same session
  are allowed without asking again. When the clock passes it, the next ask uses
  a new generation. "Once" does not start a grant. If the answer is missed, the
  next ask is new and Hermes's memory of the old key does not apply.
- **A person, not a policy.** If Hermes would grant the approval without
  asking anyone (approvals switched off, yolo, or a cron, single-query or
  unattended run whose mode is set to approve), the call is blocked. A
  scheduled job cannot lower its own guardrails.
- **Nobody there, no change.** If there is no one to ask, the call is
  blocked.

### `never`

Every agent-originated change to a guardrail is blocked. Each attempt is an
event and raises the session's score as today. Operators change settings
where the agent is not the actor: the Hermes Desktop settings form, their own
terminal, or the console.

## Making `never` concrete: pinning

Blocking depends on recognising the change in a tool call. Petasos sees paths
and command strings; an agent with a shell, running as the same operating
system user as the operator, can in principle disguise a write well enough to
slip past recognition. That is the "plastic barrier" case, and it is true of
any guard that lives in the same account as the thing it guards.

The fix is to put the settings somewhere the agent's account cannot write.
Hermes has a machine-level config (`/etc/hermes/config.yaml`) that can pin
keys so that profile config and the plugin API cannot override them. Pinned
there, in a file owned by the administrator account:

- a disguised write to the profile's config has no effect, because the pinned
  value wins;
- changing a guardrail takes the operating system's administrator password,
  which is the "prove you are the operator" step, with no separate Petasos
  password to invent, store or leak.

`petasos hermes pin` previews the current values. `--write` either replaces
an already writable managed file atomically, or prepares the complete merged
document in a new private directory and prints `mkdir` and `install` commands
for a person to run with administrator rights. Petasos never invokes a privilege
helper. The administrator never runs Petasos or Python: those files still
belong to the agent's account. Run `petasos doctor` afterwards to verify what
was installed. The JSON document is also valid YAML.

The document holds both complete plugin lists, the effective plugin-check
timeout, `enabled`, `role`, `level`, and all 77 resolved config fields under
`overrides`, including default values and empty mappings. Lists are single
managed values. The whole plugin selection stays fixed: enabling or disabling
any plugin in a profile has no effect while the lists are pinned. Pin refuses
when Petasos is absent from the enabled list or present in the disabled list.
The managed file applies to **every profile using that directory**, rather
than only the profile the command reads. Unrelated managed keys are retained.
A small `petasos_managed_pin` record tracks segment paths for removal, including
rule IDs containing dots. Unpin removes those keys and its record, preserving
unrelated keys and entries added to formerly empty groups.

`petasos hermes unpin` previews removal. When the profile differs from the
managed values, it lists the differences and refuses even with `--write`.
`--accept-profile-changes --write` explicitly accepts the values that will take
effect. Defaults omitted from a profile do not count as differences. Both
commands accept `--home` and `--profile`; Hermes also registers `hermes petasos
pin` and `hermes petasos unpin`.

### Verified limits

Real Hermes v0.23.1 was exercised only in `/tmp/petasos-s1b-sbx`, with a
per-home managed directory and an inactive machine-location stand-in. No real
machine file or administrator command was used. Tests are in
`tests/hermes_host/test_pin.py` and `pin_harness.py`.

- A stored-overrides-only pin leaves a new sibling writable. Resolving the
  entire tree before pinning closes that gap for ordinary scalar/list leaves.
  Plugin API writes and the implementation of `hermes config set` were tried
  against all 80 setting paths (the three switches plus the 77 config fields).
  The Petasos settings form and `petasos config set` were tried against those
  paths too. Hand edits were also exercised. Fixed leaves kept the values
  returned by `ctx.get_config`. The actual `hermes plugins disable petasos`
  command changed the profile, but a new process still loaded Petasos. Unpin
  restored unpinned writes and retained an unrelated managed model setting.
- **Petasos reads a pin whole, because Hermes's merge alone cannot fix this
  tree.** When the managed file carries the `petasos_managed_pin` record,
  Petasos takes its four settings from that file and does not use the
  profile's at all (`petasos.hermes.settings.pinned_settings`, checked before
  the profile is read, so a missing or damaged profile file does not unpin
  anything). The settings form locks every field, and the form, `petasos
  config set` and `petasos config migrate --write` refuse to save, because a
  save would be stored in the profile and then have no effect. The two gaps
  below are what Hermes's own overlay leaves open. They still show in
  `ctx.get_config`, and they still apply to a managed file written by hand
  without the record, which the doctor reports as partly pinned. They do not
  reach Petasos under a pin. The sandbox confirmed it: after a hand edit that
  added entries to all three groups, Hermes's merged view held them and the
  settings Petasos built did not.
- In Hermes's overlay, new
  entries can still be added to `rules.severity_overrides`, `tools.aliases`,
  and `frequency.weights`. An empty managed mapping is marked managed, but
  does not erase a profile mapping. Hermes's save APIs strip some of these
  writes; a hand edit still survives the overlay. A nonempty managed mapping
  fixes its existing entries, leaving new siblings open.
- A pinned `null` does not replace a profile mapping. At the current defaults
  this affects `scanners.presidio.entities`, `scanners.semgrep.engine_path`,
  `scanners.semgrep.engine_sha256`, and `frequency.weights`. The sandbox
  confirmed that a hand-written mapping survives in `ctx.get_config`.
  Invalid values are still rejected by Petasos; this is a limit on the pin,
  not a recommendation to store invalid values.
- Environment references are expanded by Hermes before the snapshot. A
  still-unresolved reference is refused, so a later environment change cannot
  alter a value the command calls fixed. The sandbox confirmed both a frozen
  expanded language and refusal of an unresolved reference. Manually installed
  references are named by the doctor.
- The hook timeout is pinned at **Hermes's effective value**: default 30
  seconds, a negative or invalid value uses 30, a value above 600 is clamped,
  and zero is preserved. Sandbox tests covered zero, negative, and the cap,
  then a hand edit and a refused `hermes config set`. Zero runs the hook
  inline; it does not switch the hook off. The command does not silently
  change the operator's current timeout policy.
- Changing `HERMES_MANAGED_DIR` bypasses the machine file; the doctor detects
  an inactive machine pin when it can read that file. Safe mode, changing the
  plugin's files or Python environment, and changing the event record remain
  outside the pin. The plugin's files, the Python environment and the event
  record still belong to this account. A pin fixes settings and the plugin
  list; it is not a guarantee.
- Hermes has a POSIX `/etc/hermes` default, including on macOS, and no native
  Windows location. Petasos offers no default Windows pin location and writes
  nothing there; an explicit managed-directory override can name an existing
  provisioned directory. Windows behavior is source-checked and unit-tested,
  not run on Windows.

### Doctor and Overview

The doctor reads managed scope through Hermes's own readers. Missing or
raising functions, malformed files, or a backend that ignores a managed file
produce an unknown result, never a pinned claim. It uses the effective
settings and plugin lists for its ordinary checks, and separately compares
the profile's own file. Profile-bound adapter reads apply Hermes's overlay too.
The status API includes `pin` facts; the Overview displays the same words.

| State | What it says |
|---|---|
| open | Open. The agent can change guardrails with a fresh approval. |
| blocked | Blocked. The agent is not allowed to change guardrails from the conversation. Recognition can still be evaded. |
| pinned | Pinned. Settings are fixed at machine level. Only an administrator can change them. The file carries the pin's record, both plugin lists and the timeout, and this account cannot write it. |
| partly pinned | Partly pinned. Some settings are not fixed at machine level. A plugin list or the timeout is missing, or the file was written by hand without the record, in which case the open groups and unset values are named. This is a warning. |
| writable | Pinned where this account can write. This does not protect settings from this account. The directory and the file are checked. This is the expected sandbox state. |
| not in force | Pin not in force. Hermes was pointed at a different managed directory. This is a failure. |
| profile changed | The profile differs from the pin. Something tried to change a guardrail. Pinned values are in force. Differences are named. For a file written by hand, new group entries may already take effect. |
| off in the pin | The pin leaves Petasos turned off. It is not protecting this agent. This is a failure, including when either plugin list disables it. |

Every pin state includes the limits on files, Python and the event record.
An unknown reader says: “This Python cannot tell which settings Hermes fixes
at machine level.” Non-writable state classification and the administrator
staging route are unit-tested; actual administrator ownership was deliberately
not exercised on this machine.

## Evidence

Every settings change the enforcer applies is written to the event spool,
with the setting paths, the new values of ordinary settings, and whether a
self-change approval was live in any session. The applied tree has no secret
fields, so the event does not carry a secret value. A change the operator
did not make is then visible in the console and to `doctor`, whichever way
it got in.

## What is built

- **Config.** `tools.self_change` (`approve` or `never`, default `approve`,
  owned by the role, `support` sets `never`) and `tools.self_change_minutes`
  (default 30, whole minutes from 1 to 1440). 1440 is one day: a messaging
  session can live longer than that, and a longer grant would be a standing
  approval.
- **Recognition.** `petasos.guard.guardrail` matches paths and commands. The
  Hermes adapter supplies its paths and command patterns on
  `HostInfo.guardrail_surface`. The library matches its own package directory
  and its own commands. The guard calls that unit. Reading is not a change.
- **Enforcer.** A recognised change is decided before the rest of the ladder
  and can only make the outcome stricter. `never` blocks. `approve` holds the
  call unless a live session grant covers it, and blocks when the host would
  grant the approval with nobody attached or has no approve directive. When
  Hermes can ask but nobody is attached, Petasos returns the approve directive
  and Hermes blocks the call, which is Hermes's own fail-closed behaviour.
- **Record.** Each decision is a `guardrail` event (`refused`, `unattended`,
  `held`, `covered`, `once`, `session`, `denied`). A settings change the
  enforcer applies is a `settings_changed` event: the paths, the new values of
  ordinary settings, and whether any session grant was live. Secret values are
  not written.
- **Pin commands, doctor and Overview.** Managed settings and plugin lists,
  safe staging, deliberate unpin, and the states/limits documented above.

## What is not built

- Protection against an account that can redirect the managed scope
  (`HERMES_MANAGED_DIR`) for a new Hermes process, which bypasses a machine
  pin. The doctor reports it when it can read the machine file.
- A complete answer to a disguised shell. Recognition fails closed for a
  program that is not on the small reader list, so some honest reads now ask.
  What a string match still does not catch:

  - Encoded commands (`base64 -d | sh`), text piped into a shell
    (`echo '...' | sh`), aliases and shell functions, and command
    substitution inside double quotes (`"$(...)"`). Nothing is decoded or
    executed. `eval` of a plain string, `sh -c`, and a substitution written
    outside quotes are read.
  - A shell variable that holds the program (`cmd=hermes; $cmd ...`), and
    arguments supplied when the command runs (`... | xargs hermes plugins
    disable`).
  - A directory above the Hermes home (`rm -rf ~`, `rm -rf /`). A directory
    at or inside the home that holds a protected path is a change
    (`rm -rf ~/.hermes/plugins`), and so is a wildcard there that covers one.
    Anything further up is left to the destructive-command rules. The same
    holds for the Python environment Petasos is installed in.
  - A `cd` in an earlier tool call. A `cd` earlier in the same command is
    followed. Because the directory a command really runs in is not known, a
    relative name is also tried against `HERMES_HOME` and `HOME`, so writing
    a relative `config.yaml` or `.env` asks wherever it is.
  - Nested braces (`{a,{b,c}}`), and a wildcard after `shopt -s dotglob`.
  - In a script handed to PowerShell or cmd (`powershell -Command "..."`,
    `cmd /c "..."`), which is read with that shell's rules: `-EncodedCommand`,
    `-File`, and a path or command built at runtime inside the script. See
    `hermes-host-facts.md`, section 19.
  - Anything past the first 64 commands or the first 100,000 characters of
    one tool call. The rest is not read, so padding hides a change. The
    limits bound the time a check takes, which is mostly resolving paths.
  - Package managers other than `pip`, `pipx` and `uv` (`poetry`, `conda`),
    and an install from a requirements file or from the current directory.
  - A Python path built in a variable and used later
    (`root = os.environ["HERMES_HOME"]` then `open(root + "/config.yaml")`).
    A path written next to `Path.home()`, `expanduser`, or a lookup of
    `HERMES_HOME` is recognised. A bare relative name in program text is
    recognised only when it resolves against the working directory, `HOME`,
    or `HERMES_HOME` the same way a shell word does.
  - The body of a script file the command only names (`python write.py`).
    Program text on the command line is read: `python -c`, a here-document
    given to `python`, and the arguments of `node`, `perl`, `ruby`, `php`,
    `awk` and `sed`.
  - A protected path that is only inside a larger shell argument
    (`echo 'see …/config.yaml'`). The path has to be an argument the program
    acts on, or a redirect target. Option values glued on (`--output=path`,
    `-o/path`) count. `name=path` on a word that is not an option does not.
  - `echo`, `printf`, and the other programs whose arguments are never file
    operands (`basename`, `dirname`, `expr`, `false`, `pwd`, `seq`, `sleep`,
    `true`, `uname`, `uptime`, `whoami`, `yes`, `:`). A redirect into a
    protected path is still a change. A comment in program text is not: a
    `#` outside a string runs to the end of the line, and a `#` inside a
    string stays. An unclosed string swallows the rest of the text, which
    is the approximation.
  - A plain read in program text. `open` with no mode, or a literal `r`,
    `rb` or `rt`, and `Path` / `pathlib.Path` followed directly by
    `read_text`, `read_bytes`, `exists`, `is_file` or `stat`. A write or
    append mode, a mode that is not a literal, the path assigned to a name,
    or the path passed to any other call is a change. `hermes` or `petasos`
    with `--help` or `-h` is not a change, unless the command writes
    Hermes's configuration (`hermes config set|unset|edit|migrate`,
    `hermes import`, `hermes plugins disable petasos`,
    `hermes plugins enable petasos --allow-tool-override`,
    `hermes plugins install petasos --enable`,
    `hermes plugins auto-update on|off`, `hermes plugins pack install` and
    the other settings commands), which is a change with or without one. A
    help word after `--` is not counted.

    The recogniser does not parse shell comments, and text it cannot fully
    model never removes a match. A word that starts with `#` stays a word,
    and so do the words after it, on the same line and on later lines, in
    shell text and in an argument list joined into text. Because a shell
    may read such a word as the start of a comment, it can only stop later
    words from loosening a decision: a help word after it does not count as
    help, and it and the positionals after it do not name a target, so
    `hermes plugins update # note` and `$(hermes plugins update # note)`
    update every plugin. A word after it that names Petasos, or a flag such
    as `--apply`, still counts. A configuration key matches a guarded key
    only as a whole dotted segment, so `approvals_backup` is not
    `approvals`.

  Reads that are not on the reader list now ask. That includes `sed` and
  `perl` even without `-i`, `awk`, editors (including a read-only `vim -R`),
  `git` commands that name the file, `strings`, `od`, `hexdump`, `sort`,
  `tar`, `ack`, and `ag`. `rg` is treated as a grep and does not ask. A
  read behind a wrapper or a shell keyword (`sudo cat`, `timeout 5 cat`,
  `if grep -q ...; then`) is still a read.

  `hermes`, `petasos`, `pip` and `uv` take verbs and names, and their forms
  that change a guardrail are listed as rules. For those four a bare word is
  not read as a path, so `petasos doctor` does not ask in a directory that
  happens to hold a `petasos` folder.

## Behaviour change

This is a deliberate change from 0.5, where a guardrail write is allowed
below tier 2. The frozen enforcement record is not rewritten. The new
decision, the guardrail event, and the settings-change events are named in
`tests/enforce_parity/differences.json`. The guard corpus did not change.
`docs/architecture/changelog-pending.md` names the break.
