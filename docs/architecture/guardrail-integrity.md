# Guardrail integrity

Status: the decision is built (2026-11-10) on branch `redesign/s1a-guardrail-integrity`.
Pinning is not built. Supersedes the "self-protection" notes in section 7.4 of
`redesign.md`. Where this file and the implementation brief differ, the brief
wins: the frozen enforcement record is kept and the new outcomes are named in
`tests/enforce_parity/differences.json`, and `pin` / `unpin` are not commands yet.

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

Today Petasos does neither. A write to its own config raises an event and the
session's score, and is allowed while the session is below tier 2.

## What counts as a guardrail

Anything whose change would stop or weaken enforcement, or hide that it
happened:

- Petasos's settings (`plugins.entries.petasos` in the profile's config) and
  its two secrets in the profile's env file.
- Whether the plugin runs: the plugin directory, Hermes's enabled and disabled
  plugin lists, safe mode, the hook timeout, the profile pointer, and the
  commands that change them (`hermes plugins disable|enable|remove`,
  `--safe-mode`, `hermes gateway restart`, `hermes config set` on those keys).
- The Petasos package itself (uninstalling it, editing its installed files).
- Hermes's permanent approval list where an entry would pre-approve a Petasos
  rule.
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

`petasos hermes pin` writes the current Petasos settings and the plugin's
enabled state to the machine-level config (it will ask for administrator
rights), and `petasos hermes unpin` removes them. `doctor` reports which of
three states a profile is in, in plain words:

| State | What it means |
|---|---|
| open | `approve`, not pinned. The agent can change guardrails with a fresh approval. |
| blocked | `never`, not pinned. Changes are refused wherever Petasos recognises them. A determined agent with a shell could still find a way round. |
| pinned | Settings are fixed at machine level. Only an administrator can change them. |

To verify before building: exactly which keys Hermes lets the machine-level
file pin, whether plugin enablement is among them, and the equivalent
location and permissions on Windows.

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
- **Recognition.** `petasos.session.guardrail` matches paths and commands. The
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
- **Doctor and the Overview.** Open (`approve`) or blocked (`never`), in those
  words, including the caveat that blocked is not a guarantee against a shell.
  Pinned is not offered.

## What is not built

- `petasos hermes pin` and `unpin`.
- The doctor's third state, pinned.
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
    with `--help` or `-h` is not a change.

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
