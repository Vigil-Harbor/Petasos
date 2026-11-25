# Hermes command overlap

Petasos and Hermes both judge shell commands. Hermes already detects
dangerous terminal commands and gates them through its approval prompt.
Petasos's five command rules cover the same ground for `terminal` and
`execute_code`, and then block or ask on their own. This note records what
each side actually does on Hermes v0.23.1, where they overlap, and what
changes if Petasos stops applying those rules to the tools Hermes gates.

Checked against upstream tag `v0.23.1`, commit
`3b421578588243f920886e6fe79a6faa87ea026e`. The run used a copy of the
prepared sandbox at `/tmp/petasos-s2-cmd-overlap`. `HOME` and `HERMES_HOME`
stayed inside that copy. Every Hermes import went through
`bin/with-sandbox`. No gateway, no messaging platform, and no model call.
A command was executed only when it was `echo ok`. Every other command in
this note was passed to a function as a string. The harness refuses to
execute anything else (`tests/hermes_host/order_harness.py`).

**Observed** means the sandbox process did it and the result below is what
came back. **Read** means it comes from the v0.23.1 source, with the file
and line.

## 1. Order

Hermes decides a tool call in `model_tools.handle_function_call`. Plugin
`pre_tool_call` hooks run in `_pre_dispatch_guards` before the tool handler
(`model_tools.py` lines 789–811 and 966–969). The terminal tool calls
`check_all_command_guards` after that, and only then `env.execute`
(`terminal_tool.py` lines 1548–1593 and 1114–1150). `execute_code` calls
`check_execute_code_guard` before it would spawn a kernel
(`code_execution_tool.py` lines 776–780).

Drove `handle_function_call` through the stand-in plugins, with
`approvals.mode: manual` unless a case says otherwise. The kernel spawn was
replaced with a raise, so `print("ok")` never started a child.

**Observed.** For `terminal` with `echo ok`, the order is `pre_tool_call`,
then the command gate, then `execute`, then `post_tool_call`. The command
printed `ok`.

**Observed.** For `execute_code` with `print("ok")`, the order is
`pre_tool_call`, then the script gate, then the kernel entry, then
`post_tool_call`. The kernel function was entered and then refused by the
harness. No child was spawned.

**Observed.** A plugin `{"action": "block", "message": ...}` on
`pre_tool_call` returns that message as the tool result. The command gate
does not run, the script gate does not run, and nothing is executed. This
holds for a dangerous command string on `terminal` and for `print("ok")` on
`execute_code`. `post_tool_call` still runs, as the record of a call that
already stopped. It does not get another chance to ask.

**Observed.** A plugin `{"action": "approve"}` asks inside the hook, via
`request_tool_approval` (`hermes_cli/plugins.py` lines 1196–1224). If that
ask is granted and Hermes's own gate would also ask, the person is asked
twice. On an interactive `terminal` call whose command Hermes flags, the
first prompt is the plugin rule (`<terminal> (plugin approval rule)`) and
the second is the command itself. Denying the second prompt stops the call.
The command was not executed. The same shape holds for `execute_code` when
`HERMES_EXEC_ASK=1`: the second prompt is the whole script, and the kernel
is not entered.

**Observed.** With `approvals.mode: off`, a plugin block on `echo ok` still
stops the call before the command gate. The gate's auto-approve does not
run, and the command is not executed. When the plugin does not block, the
gate runs after `pre_tool_call` and the command then runs. There is no
plugin hook between the gate's approval and `execute`. `post_tool_call`
runs after the command has already produced output, so a plugin cannot
block a command Hermes has already approved.

**Observed.** `write_file` of a two-byte text file runs `pre_tool_call` and
does not enter the command gate or the script gate.

**Read.** A block with no message is ignored, and any plugin's block beats
any plugin's approve (`hermes_cli/plugins.py` lines 1152–1167). The command
gate is reached only if the hook pass returns no block.

**Read.** Other tools that reach an approval gate, but not the
dangerous-command detector:

- `write_file` and `patch` ask for a write to SSH config or a protected
  instruction file (`tools/file_tools_write_guards.py` lines 263–268 and
  362–404). An ordinary write does not.
- `computer_use` uses the shared approval gate and fail-closes when nobody
  is attached (`tools/computer_use/tool.py` lines 382–400). This path was
  not driven.
- A plugin approve directive can send any tool through
  `request_tool_approval`. That is the plugin's ask, not the command
  detector.

The bundled `security-guidance` plugin does not look at terminal commands.
**Read.** It scans `write_file`, `patch`, and `skill_manage`, appends a
warning to the result, and blocks only when `SECURITY_GUIDANCE_BLOCK=1`
(`plugins/security-guidance/__init__.py` lines 1–8 and 104–133).

## 2. What Hermes catches

The detector is `tools.approval_detection.py`. `detect_dangerous_command`
(line 1917) returns the first match. `detect_hardline_command` (line 365)
is a separate, smaller list. The gate treats them differently.

### Hardline

**Read**, `HARDLINE_PATTERNS` lines 124–157. Twelve checks: recursive
delete of `/`, of a system directory (`/etc`, `/usr`, `/home`, `/root`,
`/var`, `/bin`, `/sbin`, `/boot`, `/lib`), or of the home directory;
`mkfs`; `dd` onto a raw disk; a redirect onto a raw disk; a fork bomb;
`kill -1`; `shutdown` / `reboot` / `halt` / `poweroff`; `init 0` or `6`;
`systemctl poweroff` / `reboot` / `halt` / `kexec`; `telinit 0` or `6`.

**Read**, `_floor_block` in `tools/approval.py` lines 1189–1212. Hardline
matches are blocked before yolo, before `approvals.mode: off`, and before
the cron, single-query, and unattended modes. Two more floors sit there:
a command that deletes this process's own Python, and `sudo -S` / askpass
password guessing when no sudo password is configured. **Observed** for
the sudo floor: `check_all_command_guards("sudo -S id", "local")` with
mode `off` returns not approved. The runtime-delete floor was not driven.

### Dangerous patterns

**Read**, `DANGEROUS_PATTERNS` lines 416–695. 114 expressions, 108 distinct
descriptions. They ask for approval. They do not by themselves block.
Grouped by what they are for:

- Delete: `rm` of a root path, recursive `rm`, long flags, flags after the
  operands, `xargs rm`, `find -exec rm`, `find -delete`, and a `find` word
  that may expand into those flags.
- Windows delete and disk: `cmd /c del`, PowerShell `Remove-Item` and its
  aliases, encoded PowerShell, `Format-Volume`, `Clear-Disk`, `diskpart`,
  `format.com`, `cipher /w`, shadow-copy deletion, `bcdedit /set`, registry
  delete, `icacls` grants.
- Unix disk and permissions: `mkfs`, `dd if=`, write to `/dev/sd`, `chmod`
  `777` / `666` / world-writable, recursive `chown` to root, `chmod +x`
  followed by `./`.
- SQL: `DROP`, `DELETE` without `WHERE`, `TRUNCATE`.
- Services and processes: `systemctl stop|restart|disable|mask`, `kill -9
  -1`, `pkill -9`, `killall -KILL` and `killall -r`, fork bomb, Windows
  `taskkill /F` and `Stop-Process -Force`.
- Remote execution: `curl` or `wget` piped to a shell, process
  substitution, command substitution, PowerShell `iwr | iex`.
- Obfuscated execution: `base64` / `xxd` / `tr` / `openssl` piped to a
  shell.
- Credentials and metadata: curl upload of a secret or a credential file,
  the cloud instance-metadata addresses, invisible and bidirectional
  Unicode in the command.
- Writes: overwrite of system config, of a project env file, or of a
  credential, SSH, or shell-rc path, by redirect, `tee`, `cp` / `mv` /
  `install`, or in-place `sed` / `perl` / `ruby`.
- Hermes itself: `hermes gateway stop|restart`, `hermes update`, launchd
  stop of the Hermes service, `gateway run` in the background, killing a
  Hermes process.
- Docker and Podman: daemon redirect (`-H`, `--context`, `--url`),
  `restart` / `stop` / `kill` / `down`.
- Git: `reset --hard`, force push, `clean -f`, force-delete of a branch.
- Sudo flags that read a password from stdin or start a shell, and
  `npm` / `pnpm` / `yarn` / `pip` / `brew` uninstall.

**Read.** The same function also flags, outside that list: `bash -c` and
other interpreter `-e` / `-c` flags, a shell heredoc, `rg` / `sort` / `ag`
/ `man` flags that run a program, a command the parser refuses because it
is too long, and a shell-spliced gateway lifecycle verb
(`_execution_flag_findings`, line 1230, and the yields at lines 1908–1914).

Three content rules are remembered on top of the first match, so approving
one pattern does not approve the other (`detect_content_rule_keys`, line
1925): invisible Unicode, a curl upload of a secret, and a credential file
piped into curl.

### What each approval mode does with a match

The gate is `check_all_command_guards` (`tools/approval.py` lines
1276–1323). The script gate is `check_execute_code_guard` (lines
1345–1415). It does not run the pattern list on the script. A fresh home's
merged config has `approvals.mode: smart` (**observed**:
`_get_approval_mode()` before any approvals block was written). The
documented default is the same (`hermes_cli/config_defaults.py` line 1657).
`cron_mode`, `single_query_mode`, and `unattended_mode` default to `deny`
(lines 1661–1662).

Called the gate functions on the strings `rm -rf /tmp/petasos-s2-not-a-real-target`
(a pattern match, not hardline), `rm -rf /` (hardline), `echo ok`, and
`print("ok")`. Nobody was prompted unless the row says so. Nothing was
executed.

| Situation | Dangerous pattern | Hardline | `execute_code` script | Plugin approve |
|---|---|---|---|---|
| Headless, mode `manual` or `smart` | Approved, no prompt | Blocked | Approved, no prompt | Blocked |
| Headless, mode `off` | Approved | Blocked | Approved | Approved |
| Interactive CLI, mode `manual` | Prompt, deny stops it | Blocked, no prompt | Approved, no prompt | Prompt |
| Interactive CLI, mode `smart` | Guardian, then the person if it escalates | Blocked, no guardian | Approved, no prompt | Prompt, no guardian |
| Interactive CLI, mode `off` | Approved | Blocked | Approved | Approved |
| Session yolo, interactive, mode `manual` | Approved | Blocked | — | — |
| Cron, `cron_mode: deny` | Blocked, no prompt | Blocked | Blocked | Blocked |
| Cron, `cron_mode: approve` | Approved | Blocked | Approved | Approved |
| Single-query (`-q`), even with `HERMES_INTERACTIVE=1`, mode `deny` | Blocked | Blocked | Blocked | Blocked |
| Single-query, mode `approve` | Approved | Blocked | Approved | Approved |
| Platform `webhook`, `unattended_mode: deny` | Blocked | Blocked | Blocked | Blocked |
| Platform `webhook`, `unattended_mode: approve` | Approved | Blocked | Approved | Approved |
| `HERMES_EXEC_ASK=1` and interactive, mode `manual` | Prompt | Blocked | Prompt for the whole script | Prompt |

**Observed** for every cell, by calling the gate. The smart row used a
stand-in for `_smart_verdict` that returned `escalate` and counted the
call. The real function was not called.

**Read** for what that function would have done. `tools/approval_smart.py`
lines 1–34 send the command to an auxiliary model and accept one word,
`APPROVE`, `DENY`, or `ESCALATE`. `APPROVE` lets the command through.
`DENY` blocks when nobody can override it, and otherwise offers the person
a one-time choice. `ESCALATE` falls through to the normal prompt. That
model call was not made.

**Read.** `HERMES_YOLO_MODE` is frozen when `tools.approval` is imported
(line 48), so a later environment change cannot turn it on. **Observed:**
setting the variable after import leaves the frozen flag false. Session
yolo is the row above.

**Observed.** `approvals.deny: ["rm -rf /tmp/*"]` still blocks that
command when mode is `off`. The message says the rule also beats yolo.

**Observed.** `check_all_command_guards("rm -rf /", "docker")` and the
same call with `vercel_sandbox` return approved. The same call with
`docker` and `has_host_access=True` is a hardline block. **Read**, lines
1282–1283: an isolated container skips the pattern list and the hardline
floor. A user deny rule still applies on that path (line 1283, the
`_user_deny_block` before the approved return).

**Read.** Interactive `execute_code` returns approved without looking at
the script because the script's later `terminal()` calls are supposed to
hit the command gate one by one (lines 1385–1394). `os.system` and
`subprocess` inside the script never do. Ask mode and a gateway session
prompt for the script as a whole instead.

## 3. The overlap, measured

Both detectors were called on strings. Petasos was
`MinimalScanner.scan(..., direction="outbound")`, which is the direction
the tool-call guard uses. A Petasos hit is one of the five command rule
ids. A Hermes hit is `detect_dangerous_command` or `detect_hardline_command`
returning a match. Neither function executes the string.

The inputs are every command-shaped string in three places:

- `tests/parity/corpus.json`: each `terminal` `command` and each
  `execute_code` `code` or `text`, in the tool cases and in session steps.
- The command examples `tests/test_minimal_scanner.py` runs: the positive
  pairs, the benign list, and the accepted false positives in
  `tests/adversarial/syntactic/benign_corpus.py`.
- The adversarial command cases: the detect pairs, the intentional misses,
  and the extra payloads in `tests/adversarial/syntactic/test_command_rules.py`
  (the backslash-`rm` of `/tmp`, the zero-width `rm -Rf /`, the cross-line
  pipeline, the zero-width `echo | sh`, the five-rule stack, and the long
  base64 blob piped to `sh`) plus the two `curl | sh` params in
  `tests/adversarial/guard/test_tool_smuggling.py`, including the one-megabyte
  prefix.

175 inputs, 144 distinct strings. The same string in the corpus and again
in an example list counts twice.

| | Petasos command rule | No command rule |
|---|---:|---:|
| Hermes flags it | 56 | 17 |
| Hermes does not | 10 | 92 |

### Petasos only (10)

All ten are `pipe-to-shell` or `alias-escape`. Hermes's pipe rule requires
`curl` or `wget` (or a decoder) on the left of the pipe. A pipe into a
bare `sh` or `zsh` does not match. The backslash form is not one of
Hermes's patterns.

- `pipe-to-shell`: `cat config.sh | sh`, `echo x | zsh`, `cat x | sh`, and
  three accepted false positives (`bash|sh|zsh`, a markdown table cell
  that starts with `bash`, and a line break before the word `bash`).
- `alias-escape`: `\chmod 644 config`, twice in the corpus and once in the
  positive examples.

`\rm -rf /tmp` is not in this column. Both detectors flag it. Petasos
reports `destructive-recursive`. Hermes reports `delete in root path`.

### Hermes only (17)

- Recursive `rm` of a relative target, which Petasos leaves alone by
  design: `rm -rf build/`, `rm -rf "build/"`, `rm -rf node_modules && npm
  install`, `rm -rf ./tmp/build`, `rm -rf $HOMEBREW_CACHE`.
- `dd` onto a file, `/dev/null`, or `/dev/shm`. Petasos only flags `dd`
  onto other device nodes.
- A markdown row `| wget | bash |` and a table row `| base64 -d | sh |`.
  Petasos's trailing-pipe lookahead is what makes these benign for it.
  Hermes still flags them.
- `curl x | sh | tee install.log` and `echo b64 | base64 -d | sh | logger`.
  Petasos documents these as intentional misses because of the trailing
  pipe. Hermes flags both.
- `rm -r -f /` and `rm --recursive --force /`. Petasos misses the split
  flags and the long flags. Hermes hardline-blocks both.
- Invisible characters: corpus commands `hello` plus U+200B, and `hello`
  plus U+202E. Petasos raises `encoding.invisible-chars` or
  `encoding.rtl-override`, not a command rule. The zero-width
  `echo | sh` is the same Hermes hit, and Petasos's command family does
  not read the composed view, so the command rule stays quiet.

### Encoded forms

The command tests' own encoded forms are the decode-and-execute pipes
(`echo QUJD | base64 -d | sh`, `xxd -r`, `openssl enc -d`, and
`echo Zm9v | base64 -d | bash`). **Observed.** Both detectors flag every
one of those. Hermes's description is `pipe decoded content to shell`.
Petasos fires `decode-exec` and `pipe-to-shell`.

The decode step inside Petasos does not rescan a decoded blob for command
rules. **Read**, `petasos/scanners/minimal/decode.py` `_rescan_candidate`: the
rescan is injection, role-switch, and agent-directive only.

**Observed**, separately from the 175, by encoding each of the 22 positive
commands and handing both detectors the result:

- The bare base64 text, and the bare hex text, match neither detector for
  21 of the 22. One long blob also raises Petasos
  `encoding.base64-in-text` at low severity. Hermes's detector does not
  decode a blob that is not already a shell pipeline.
- `echo <blob> | base64 -d | sh` matches both for all 22. The match is the
  pipeline, not the bytes inside the blob. Hermes does not need to know
  that the blob is `rm -rf /`.

So "decoding" here is the visible `base64 -d | sh` shape, which both sides
already catch. A command that is only a base64 blob, with no pipe, is
caught by neither side's command detector.

## 4. What only Petasos does

These are not pattern overlaps. They are the rest of the decision.

**Session score.** **Read**, `frequency.py` lines 34–39 and 357–366. A
command rule weighs 3.0. A tool-argument scan contributes either nothing
or one step of `tier1 / 4` (3.75 with the default tier). One rule is under
that step, so it scores 0. **Observed:** `Pipeline.inspect` of `rm -rf
/var` with that cap leaves the session score at 0. The same call on the
five-rule stack (four command rules survive the merge) scores 3.75, one
step, which is under tier 1 (15). **Observed** on the corpus session
`s-command-cap`, twelve `rm -rf /var` steps: the score stays 0 and the
tier stays `none` whether or not the command rules run. The other corpus
sessions that contain a terminal command keep the same tier sequence
either way. Their scores differ by less than 0.00001, which is the
half-life moving between the two replays.

**Fail mode.** **Read**, `petasos/enforce/calls.py` lines 364–395 and
`decisions.py` lines 226–252. If the parameter scan errors, a dangerous
tool is blocked, or asked once per session when the posture is `approve`.
Hermes's detector does not have this branch. Dropping the command rules
does not drop it.

**Taint.** **Read**, `decisions.py` lines 174–187. Content the agent read
from a tainted source is blocked on the way out to an egress tool, before
command rules are considered. Hermes does not score that.

**Encoded and obfuscated commands.** The visible decode-pipe is shared, as
section 3 says. The zero-width and homoglyph folding that Petasos applies
before the command patterns does not make Hermes's detector see
`echo\u200b|\u200b5h` as a pipe. Hermes sees the invisible character and
asks for that reason instead. A bare base64 blob of a command is invisible
to both command detectors.

**Blocking when nobody can be asked.** **Observed**, section 2. On a
headless process, Hermes approves a dangerous pattern. Petasos's default
posture is `block` (`petasos/config/sections/tools.py`). The enforcer then
blocks the call. That block is the only thing that stops the command.

**The record.** Petasos writes the block, the ask, and the tier to its
event spool. **Read**, Hermes keeps approval history for its own prompts
and does not write that spool. The observer hooks `pre_approval_request`
and `post_approval_response` do not run when the no-human path fail-closes
(host-facts section 5). A log that only listens to those hooks misses the
headless auto-approve.

**Commands in tools Hermes does not gate.** **Observed:** `write_file`
does not enter the command gate. **Read:** the pattern detector runs
inside the `terminal` tool only. `execute_code` gates the script as a
blob and does not scan it for `rm` or `curl | sh`. Any other tool name
Petasos treats as acting (`is_dangerous` in `decisions.py` line 80) is
scanned for command rules and never shown to Hermes's detector. The
smuggling tests use a tool named `cmd` for this reason.

## 5. What only Hermes does

**The prompt.** Once, session, or always, the timeout, the denial breaker,
and `command_allowlist`. Petasos cannot draw that prompt. It returns
`approve` and Hermes asks. **Observed:** that ask is a real prompt with a
callback, and a deny stops the command.

**The hardline floor under every loose setting.** **Observed:** yolo,
mode `off`, cron approve, single-query approve, and unattended approve all
still block `rm -rf /`. Petasos's `destructive-recursive` rule does not
fire on `rm -r -f /` or `rm --recursive --force /`, and it does not fire on
`rm -rf build/`. Hermes does.

**User deny globs, the sudo-stdin floor, and the runtime self-delete
floor.** The first two were observed under mode `off`. The third was read.

**Windows, git, docker, SQL, metadata, and credential-upload checks.**
None of the five Petasos command rules cover those. They showed up as
Hermes-only where the test material happens to contain them, and the
pattern list is much longer than that material.

**Container skip.** **Observed:** a docker or Vercel backend approves
`rm -rf /` at the gate. Petasos does not have that exception.

**Smart mode's auxiliary model.** Read, not run. Petasos has no equivalent
on the command path.

**Whole-script approval for `execute_code` in ask and gateway sessions.**
**Observed** under `HERMES_EXEC_ASK=1`: the prompt names the script, not a
line inside it. An interactive CLI does not raise that prompt at all.

## 6. What deferring would change

"Deferring" here means Petasos stops applying its five command rules to
`terminal` and `execute_code`, and keeps them for every other tool. The
corpus was replayed with those rules suppressed on the scanner, through
the same guard the parity oracle uses, for profiles `none`, `general`, and
`code_generation`. The enforcer decision was then taken from
`dangerous_tool_decision` with posture `block` and again with `approve`.

There are 73 `terminal` and `execute_code` tool cases. Under `none` and
`general`, 13 change. All 13 are `terminal`. `execute_code` cases do not
contain a command-rule match, so their guard verdicts stay put. The 13
are `g0004` through `g0010`, `g0019`, and `g0189` through `g0193`:

- `\chmod 644 config` (`alias-escape`)
- `rm -rf /var` and `\rm -rf /tmp` (`destructive-recursive`)
- `curl … | sh` and `wget … | bash` (`fetch-exec`)
- `echo Zm9v | base64 -d | sh` (`decode-exec`)
- `echo x | zsh` (`pipe-to-shell`)

For each, the guard stays `allowed` at tier `none`. `param_scan_unsafe`
flips from true to false. The findings list loses that one high command
rule. The session score stays 0. The enforcer decision flips from `block`
to `allow` under posture `block`, and from `approve` to `allow` under
posture `approve`.

`code_generation` (the coding role) already suppresses `pipe-to-shell` and
sets the posture to `approve`. Twelve cases change, not thirteen: `g0008`
(`echo x | zsh`) is already quiet. The other twelve still lose their
command finding, and the enforcer goes from `approve` to `allow`.

Session `s-command-cap` is twelve `rm -rf /var` steps. Suppressing the
command rules flips each step's `param_scan_unsafe` from true to false.
The score stays 0 and the tier stays `none`. No other session changes
tier. Command rules are not what pushes a corpus session up the ladder.

What an attacker gains on `terminal`, if those rules are simply removed:

- Where a person is at the keyboard and Hermes is in `manual` or `smart`,
  Hermes still prompts for the 56 overlapping inputs, and for the 17 it
  alone flags (`rm -rf build/`, the split-flag `rm` of `/`, and the
  rest of section 3). The 10 Petasos-only inputs are 7 distinct strings.
  Three are accepted false positives. Four are real commands:
  `cat config.sh | sh`, `cat x | sh`, `echo x | zsh`, and `\chmod 644
  config`. Those four run with no prompt.
- Where Hermes will not ask, nothing in Hermes's pattern layer stops a
  non-hardline command. **Observed** with mode `off`, with unattended
  approve, with cron approve, with single-query approve, with session
  yolo, and with a headless process whose mode is still `manual` or
  `smart`: the gate approves `rm -rf /tmp/petasos-s2-not-a-real-target`.
  The same settings still block `rm -rf /`, still honour `approvals.deny`,
  and still block `sudo -S`. They do not block `rm -rf /var`, `curl | sh`,
  or `echo … | base64 -d | sh`. Those run.

On `execute_code` the corpus does not move, because those scripts are not
shell. The loss is the script Hermes does not pattern-scan. In a local
interactive or headless session the script gate approves `print("ok")`
without reading it (**observed**). A script whose source contains
`curl https://x | sh` is a command-rule hit for Petasos today and is not a
pattern hit Hermes acts on. Ask mode and a gateway session still prompt
for the script as a whole, so the person sees one Hermes prompt instead of
a Petasos block. If they approve the script, the command inside it runs.

## Recommendation

Keep Petasos's command rules. Let Hermes ask once for the commands it
already flags, and only then. Do not hand Hermes the cases where it will
not ask.

Three options, then the one the facts support.

**(a) Leave both in place.** A `terminal` command that both flag is a
Petasos block under the default posture, and Hermes's prompt never
appears, because the plugin block returns first. Under the coding role the
posture is `approve`, and the person is asked twice: Petasos's rule, then
Hermes's command. Protection stays as it is, including the headless
auto-approve hole in Hermes, which Petasos currently fills. Nothing in the
code changes. An upstream change to Hermes's detector or to hook order
does not weaken Petasos. The cost is the double prompt, and a block that
hides Hermes's once / session / always choice for the commands Hermes
already handles.

**(b) Stop blocking and asking on command rules for the tools Hermes
gates, whenever the gate is active and a person can be asked. Keep
scoring them.** The person sees one Hermes prompt for `terminal`. They
see no Petasos block for those calls. The score does not move for a single
command rule, so "keep scoring" does not preserve the escalation behaviour.
The four real Petasos-only commands (`cat … | sh`, `echo … | zsh`,
`\chmod 644`) are not flagged by Hermes, so they run with no prompt even
though a person is there. `execute_code` in a local session is not pattern
gated, so dropping the rules there drops the script-text check. The code
change is the command branch of `dangerous_tool_decision` in
`petasos/enforce/decisions.py`: for `terminal` and `execute_code`, skip the
block and the approve when a new host fact says a person can be asked.
The adapter in `petasos/hermes/` is what knows that fact (interactive,
gateway, or ask; mode `manual` or `smart`; not yolo; not mode `off`; not a
cron, single-query, or unattended approve context). If upstream stops
running the gate after `pre_tool_call`, or starts auto-approving an
interactive session, this option goes soft without a test failing unless
that host fact is pinned.

**(c) Full deferral for `terminal` and `execute_code`.** Delete the command
rules for those two tools in every mode. The 13 corpus verdicts above
become allows. `s-command-cap` stops marking those steps unsafe. With
Hermes approvals off, or an unattended run set to approve, or a headless
process that never sets a cron or single-query marker, a non-hardline
command is not stopped by either system. Hardline, `approvals.deny`, and
the sudo-stdin floor still fire, and only those. A container backend that
skips the pattern list (docker without a host mount, Vercel) would no
longer have Petasos's check either. The code change is the same branch,
with no host fact. Upstream can loosen `approvals.mode` and Petasos will
not notice.

**(d) Defer only the calls Hermes will both see and ask about.** This is
the option that fits both of the owner's wishes.

On a `terminal` call, skip the command-rule block and the command-rule
approve only when both of these are true: Hermes's detector flags that
command string, and a person will actually be asked (the host fact in
(b)). Record the finding in the spool anyway. Leave the session score
alone; one command rule does not reach it. In every other case, keep
today's decision:

- Hermes does not flag `cat x | sh`, `echo x | zsh`, or `\chmod 644`.
  Petasos still blocks or asks on those, so the Petasos-only column does
  not become a hole.
- Hermes would auto-approve (headless, mode `off`, yolo, cron approve,
  single-query approve, unattended approve, container skip). Petasos still
  blocks. Turning Hermes's approvals off does not turn Petasos off.
- The tool is `execute_code` or anything else. Hermes does not run the
  pattern detector on that text. Petasos keeps the five rules there.

The person at an interactive `terminal` then sees one Hermes prompt for a
command both sides flag, and still sees a Petasos block for a command only
Petasos flags. A headless or approve-mode run sees the same Petasos block
as today. Of the 13 corpus cases, `\chmod 644 config` (`g0004`, `g0189`)
and `echo x | zsh` (`g0008`) stay a Petasos decision, because Hermes does
not flag them. The other ten are commands Hermes flags. They become one
Hermes prompt when a person will be asked, and they stay a Petasos block
when Hermes would auto-approve. They do not become a silent allow.

The code change is local. `dangerous_tool_decision` gains a predicate,
supplied by the host, "this terminal command is one Hermes will ask a
person about". The Hermes adapter implements it by calling
`detect_dangerous_command` or `detect_hardline_command` on the command
string and by reading the same mode and presence bits section 2 lists. It
does not copy the pattern list. The predicate must be false when the
container skip would approve the call, or (d) collapses into (c) on
docker. A test next to `tests/hermes_host/test_command_gate_order.py`
should pin the predicate against the live gate: when the gate would
prompt, the predicate is true; when the gate auto-approves, it is false.

If upstream reorders hooks so the command gate runs before
`pre_tool_call`, (d) still blocks too late to matter and the order tests
fail. If upstream changes the detector, Petasos follows it, because it
calls the function instead of copying it. If that function moves or
disappears, the adapter should fail closed (keep the Petasos decision),
not fail open.

(a) is the safest and it fights the prompt Hermes already shows. (c) is
the cleanest and it goes soft the moment Hermes's settings do. (b) avoids
the double prompt and still goes soft for the four commands Hermes does
not flag, and for every `execute_code` script. (d) is the one that uses
Hermes where Hermes actually decides, and keeps a block where Hermes will
not.

## Decision, 2026-11-10

The owner chose the asking route. Two things follow, and they are built
together.

**The general job asks.** `general` sets `tools.dangerous_posture` to
`approve`, as `coding` already does. A risky tool call is put to a person
where one can be asked, and is blocked where nobody can: a headless run, a
cron job, Hermes approvals switched off, yolo, a host with no way to ask.
`research`, `support` and `admin` keep `block`. A research agent reads and
has little call for a risky command. A support agent's conversation is
with an outsider, who must not be the one asked. An admin agent holds
powerful access.

**Hermes asks once.** Option (d), narrowed: Petasos stands aside for a
`terminal` call only when its own posture is `approve`, Hermes's detector
flags the command, and a person will be asked. It records the finding and
lets Hermes's prompt be the one the person sees. Where the posture is
`block`, a block stays a block. Where Hermes does not flag the command, or
would approve it without asking, or the tool is not `terminal`, Petasos
decides as it does today.

An upgrade does not loosen anyone's settings without their choosing it.
`petasos config migrate` writes `tools.dangerous_posture: block` for a
configuration converted from the old `general` profile, and says so.

## Decision, 2026-11-15: beside Tirith

The owner's principle is: "I would ideally not overlap jobs and allow Tirith
to take the lead for its domain."

Tirith now leads on shell command text when its plugin is loaded beside
Petasos. In an asking role, Petasos leaves `pipe-to-shell`, `decode-exec`
and `fetch-exec` to Tirith, only for `terminal`. This requires no yolo and
no host setting that would grant an approval with nobody attached. A denied
unattended approval is still a decision by the host; an unattended approval
that would run the command is not protection to stand aside for.

`alias-escape` and `destructive-recursive` keep the November 10 decision.
For mixed command findings, every remaining finding must have an owner:
Tirith for the three execution rules, or Hermes's own prompt under the
existing predicate for the rest. Otherwise Petasos makes its usual decision.
A standing Petasos rule approval removes that finding before this check.
Hardline commands keep Hermes's refusal. Taint, non-command findings,
personal data leaving through an egress sink and a degraded parameter scan
are never handed over. Neither `process_manage` nor `execute_code` gains
this exception.

A blocking role still blocks. The owner chose that on 2026-11-15: "I lean on
keeping the Petasos block." In an unattended run where Hermes grants every
ask, it is the only stop for these commands.

The host supplies a callable fact and a display name; enforcement has no
knowledge of Hermes or Tirith. The Hermes adapter calls the public
`ctx.has_plugin("tirith")` at decision time, after plugin loading. Reading it
in `register` would miss Tirith, because Petasos loads first. A missing or
raising probe answers no. The current context is replaced on re-registration,
so a reload does not retain the previous manager's plugin status. No Tirith
module or private state is read. No `requires_plugins` dependency is added:
Hermes warns when that optional plugin is absent. See host facts section 18
for the upstream source and sandbox evidence.

Activity names who received the finding. Try it shows that Petasos lets the
call proceed to that checker; it cannot predict the checker's verdict.
Doctor adds a plain explanation when the current Hermes has both plugins
loaded. Result annotation stays as it is; the collision and the earlier
terminal-output hook are investigated in host facts section 18.

## Built

This is what the code does.

The `general` role sets `tools.dangerous_posture` to `approve`. `research`,
`support`, and `admin` stay `block`. `petasos config migrate` pins `block`
on a configuration converted as `general`, and the note says the old profile
blocked and the conversion does not start asking. A section that already
names `dangerous_tool_posture` keeps that value.

`HostInfo.command_judge(command)` returns `CommandJudge.PERSON`,
`GUARDIAN` (guardian then a person if needed), or `NOBODY` (the default).
The Hermes adapter calls `detect_dangerous_command` and reads the same mode,
yolo, presence, allowlist, session-approval, and container facts section 2
lists. It does not copy the pattern list. A missing, moved, or raising helper
answers nobody. After hosted-room overrides, `manual` names the person and
`smart` names the guardian; other modes name nobody.

**Smart approval, built 2026-11-17.** Petasos stands aside only for a
`terminal` command-rule finding under posture `approve`, when the host would
not grant an approval with nobody attached. A person-owned command keeps the
manual behavior. A guardian-owned command is left to Hermes only while the
guard's conversation tier, read at decision time, is below `tier1`. At
`tier1` or above, or if the tier cannot be read, Petasos asks the person
itself. Hermes's later guardian or prompt may still follow in that case.
One earlier flag below `tier1` does not change this rule. Tirith's ownership
of its three command rules is independent of tier.

The `deferred` event names its owner and carries the conversation's score
and tier. Activity says "Hermes's smart approval will judge this" for the
guardian. The scan still scores as before; deferral adds and removes no score.
The call proceeds to Hermes's gate, with no approval verdict made by Petasos.
See the [settled proposal](smart-approval-proposal.md).

Hardline commands are not that case. Hermes refuses them without asking, so
the predicate answers no and Petasos decides as it does today. The command
does not become a silent allow: Petasos blocks or asks, and Hermes's floor
still refuses unless a container backend skips the gate. A container skip
answers no as well, so Petasos's decision is what stands in front of it.
Taint, a non-command finding, PII leaving through an egress sink, and a
degraded parameter scan are not stood aside from. A block posture stays a
block.


Beside Tirith, `HostInfo.command_checker` is a callable returning the loaded
checker's name or none (`petasos/enforce/types.py` lines 167–187).
`petasos/hermes/plugin.py` lines 332–346 implement the runtime probe;
`host_info` supplies it and names Hermes's prompt at lines 357–364. The
registration updates its context on every `register` call.
`petasos/enforce/calls.py` lines 397–415 pass those facts and the same
unattended-grant condition as before. `decisions.py` lines 302–342 require
an owner for every remaining command finding and emit `deferred_to`.
No scoring code changes: the parameter scan still runs and contributes as
before; the decision adds no score and removes no score.

`petasos/hermes/dashboard/words.py` renders the recorded owner; Activity's
aggregate uses "Left for another check" because several owners can occur.
Old records without an owner retain their Hermes wording. The playground
uses the live checker and unattended-grant facts
(`petasos/hermes/dashboard/playground.py` lines 508–540). Doctor's extra
line is in `petasos/hermes/doctor_report.py` lines 143–154.

The behavior tests are in `tests/enforce/test_decisions.py`,
`tests/enforce/test_enforcer.py`, `tests/hermes/test_plugin.py`, and the
Activity, playground and doctor tests.
`tests/hermes_host/test_smart_approval.py` exercises guardian approve, deny and
escalate stand-ins, manual mode, cron and single-query modes, and tier1.
No model is called. `tests/hermes_host/test_tirith.py`
loads only a stand-in named `tirith`: the fetch-exec call passes Petasos,
writes a named deferred event, then Hermes denies execution. Only `echo ok`
is ever executed by that harness.

## Smart approval, read 2026-11-17

Read from Hermes `v0.23.1` source (the sandbox checkout of that tag) and its
documentation. Nothing was executed and no model was called. Line numbers
are from that checkout.

- **What reaches the guardian.** Only `check_all_command_guards`
  (`tools/approval.py:1322`) and `check_execute_code_guard` (`:1413`) pass
  `smart=True`. The plugin approval gate, file-write guards and computer use
  never reach it. The floors, yolo, the allowlist, presence and remembered
  approvals are checked first (`:1282-1316`). Cron, single-query and
  unattended platforms are settled by their `*_mode` before it (`:1303-1308`).
- **What it sees.** A fixed system prompt plus the operator's
  `approvals.smart_policy`, then "The following command was flagged as:
  {description}" and the command with comments stripped
  (`tools/approval_smart.py:103-122`). No conversation, tool name, history or
  plugin reason. The description is Hermes's own pattern findings
  (`approval.py:731-749`), including content rules ported from Tirith
  (`tools/approval_detection.py:721`).
- **Verdicts** (`approval.py:882-911`). APPROVE lets that command through.
  DENY blocks; with a person present the owner may override once. ESCALATE,
  an unknown answer or an error falls through to the person's prompt.
- **"Classifier"** in Hermes means this auxiliary `approval` task
  (`hermes_cli/config_defaults.py:751`). There is no classifier registry. A
  plugin cannot register the `approval` task (`plugins_aux_tasks.py:28-30`).
- **A plugin's approve request** goes to a person, never to the guardian, and
  does not use the selected approval transport (`approval.py:864-867`,
  `plugins.py:1214`). Without `rule_key` the remembered answer covers the
  whole tool; Petasos always sends one (`petasos/hermes/plugin.py`).
- **Conventions.** Hermes documents no plugin approval policy or auto-allow
  callback (`website/docs/user-guide/features/plugins.md:339-345`). Catalog
  rule 12: "A plugin never routes around Hermes's approval system: no
  auto-approving" (`plugin-catalog/README.md:108-113`). Plugins that veto or
  escalate a command do it from `pre_tool_call` (`approval.py:1279-1280`).
- **Tirith** is no longer bundled; its catalog entry sends its asks to
  Hermes's approval prompt (`plugin-catalog/tirith.yaml:10-12`). Nothing ties
  it to smart mode. The real plugin's source was not read.

Open: a real guardian's behaviour, especially on `execute_code`; whether a
plugin's ask and Hermes's later prompt for the same command are always two
prompts (inferred from their different approval keys).
