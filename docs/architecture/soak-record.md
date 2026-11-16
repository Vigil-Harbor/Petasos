# Soak record: the researcher, 2026-11-13 to 2026-11-16

Petasos ran inside a real, working Hermes for three daily cycles. This is
what ran, what it showed, and what to fix before release. Counts come from
the kanban database, Petasos's event record and Hermes's logs for the
profile, all read back afterwards.

## What ran

- **Host.** Hermes `v0.23.1` from a source checkout, started by launchd
  through Hermes's own launcher, one gateway with a messaging platform attached and a
  local model. The profile is a named profile under a shared root. Hermes
  approvals are `manual`.
- **Work.** An unattended morning cycle of ten kanban cards: one research
  card, eight paper-ingest cards and one wiki finalize card. The agent reads
  and edits a wiki of about 1,900 markdown pages, searches it, runs a few
  terminal commands and fetches a few web pages.
- **Petasos.** 0.4.0 from `arch/redesign` at `d519061`, installed with
  `petasos hermes install` and turned on with `hermes plugins enable
  petasos`. Job `research`, strictness `relaxed`. Built-in checks only:
  Presidio and PromptGuard were not installed and Semgrep was off. The
  version stayed the same for all three cycles.
- **Not exercised.** Nothing was blocked or put to a person, so the block
  and approval paths did not run on the live install. No setting changed
  while the gateway ran. Tirith was not present.

## The three cycles

Days without Petasos, 2026-11-10 to 2026-11-12, set the latest finish time.

| | 2026-11-14 | 2026-11-15 | 2026-11-16 |
|---|---|---|---|
| Cards done, of 10 | 10 | 10 | 10 |
| Failed, retried or blocked cards | 0 | 0 | 0 |
| Finished, against the latest day without Petasos | 3 minutes earlier | the same time | 6 minutes earlier |
| Conversations checked | 10 | 10 | 10 |
| Tool calls | about 160 | 191 | 160 |
| Scans completed | 266 | 314 | 263 |
| Flags on tool results | 5 | 7 | 5 |
| Blocks, asks, guardrail events, escalations | 0 | 0 | 0 |
| Hook errors or timeouts | 0 | 0 | 0 |

`hermes petasos doctor` said Protected on each day. The gateway ran
unchanged from 2026-11-13 to the end.

**Cost.** A file read took a median 0.10 s on 2026-11-15 and 0.09 s on
2026-11-16, against 0.06 s on 2026-11-12 without Petasos. The slowest read
was 0.55 s and 0.59 s against 0.24 s. Those are reads of about 100,000
characters. The cycle as a whole finished at its usual time.

## False positives

All 17 flags were false positives. Each was the rule
`petasos.syntactic.injection.agent-directed-fetch`, rated high, on a
`read_file` result holding one of the wiki's own pages. No conversation had
more than three, and three inside one minute did not raise its tier.

**Cause one, 16 of the 17: a JSON result counted as one line.** Hermes hands
a tool result to a plugin as JSON text, where a line break inside a string
is written as backslash and `n`. The rule needs a phrase such as "to the
agent", a word such as "run" and a link on one line. With no real line
breaks in the text, a whole read of 100,000 characters was one line. Fixed
in `6c9102b`: a written line break in a JSON result is read as one.
Re-scanning the 17 stored results with that fix clears 16.

The same fault hid real findings. "Ignore all previous instructions" broken
over two lines was not caught inside a Hermes result, and a phrase at the
start of a line was not seen as starting a word. Both are caught with the
fix.

**Cause two, 1 of the 17: a very long paragraph.** Two pages each hold one
paragraph of 1,900 to 2,900 characters on a single line, and the three parts
fall somewhere in it. Fixed after the soak in `108ae7f`: the three parts must
sit within 300 characters of each other.

## Five months of stored work

Three mornings are a small sample. The profile's own session store holds
every tool call and result from 2026-06-23 to 2026-11-16: 41,443 calls and
41,428 results. On 2026-11-16 they were replayed through Petasos offline, in
their original order and on their original clock, with the same job and
strictness. Nothing was executed and the live install was not touched. The
work is assumed to be benign, so every flag and block below is a false
positive unless it says otherwise.

| | As installed (`d519061`) | With both fixes (`108ae7f`) |
|---|---|---|
| Results flagged | 236 | 0 |
| Tool calls blocked | 9 | 6 |
| Conversations whose risk tier rose | 0 | 0 |

- **Flags.** All 236 were `agent-directed-fetch`: 189 on file reads, 38 on
  terminal output, the rest on code output, web pages and one card. Reading
  a JSON result line by line leaves 18. The 300-character reach leaves none.
- **Blocks removed by the fixes, 3.** The agent wrote one of the long
  paragraphs back into the wiki, twice in October, and the write was
  blocked as an instruction to an agent. On a live install that fails a
  card.
- **Blocks that remain, 6 of 41,443 calls.** Four are `rm -rf` of the
  agent's own directory under `/tmp`. The `research` job blocks recursive
  deletes, so the rule did what it is set to do, on a harmless command. Two
  are the nesting-depth check reading code as JSON, which is a false
  positive. None is later than 2026-08-29.
- **Milder findings.** Of the 30,676 results Petasos scans the text of, up
  to one in five carries a low or medium finding that raises no flag: a look-alike character, a long hash that
  resembles encoded text, a phrase such as "act as". They did not move any
  conversation's tier in five months.

## Found while installing

Each was found on 2026-11-11 to 2026-11-13 and fixed on the branch.

- **The standalone doctor could not find a named profile's environment.**
  Hermes records one environment for the whole root. Doctor looked only in
  the profile. Fixed in `ff9394b`.
- **Install named a step that cannot be done.** It said to install Petasos
  into Hermes's Python. A Hermes run by its own launcher has no such Python
  to install into. Install now writes the files and prints the Hermes
  command that turns the plugin on. Fixed in `ff9394b` and `d519061`.
- **The wheel did not carry the Petasos tab.** `petasos hermes install` run
  from an installed copy, outside a checkout, crashed looking for the tab's
  files. The real-Hermes tests had been importing the checkout by accident.
  The wheel now carries the tab and the tests run from the installed copy.
  Fixed in `d519061`.

## Host behaviour worth knowing

These are Hermes's, not Petasos's. The detail is in
[host facts](hermes-host-facts.md), section 17.

- A `manifest.json` in the directory above the checkout makes Hermes refuse
  every environment rebuild, so `hermes plugins enable` fails.
- `hermes gateway restart` rewrites the launchd service definition. On
  2026-11-13 it replaced the operator's definition and dropped the
  operator's lock and state directories. For about two minutes the gateway
  kept its locks in Hermes's default directory, not the operator's.
  Nothing else was affected. The operator's file was put back and
  the service reloaded with `launchctl`. Petasos does not print that
  command; Hermes's `plugins enable` does.
- One Python environment serves every profile under a root. Turning a
  plugin on for one profile rebuilds what the others start with next.

## The two open host facts

Neither was exercised. No setting changed during any cycle, so the record
does not show whether a settings change reaches a running gateway without a
restart, or whether a kanban worker keeps the settings it started with.

One observation, which is an inference from the logs: each kanban worker
logged a Petasos session start and no Petasos start-up. That fits workers
that begin as copies of the gateway process with Petasos already loaded.

## Before release

1. **The nesting-depth check counts brackets in code.** It is meant for
   JSON, and it reads any text. A Python script and a shell loop written by
   the agent each counted as JSON nested deeper than the limit, which is a
   critical finding and a block. See "Five months of stored work" below.
   The check is part of the frozen behaviour records, so changing when it
   applies is a decision for the owner.
2. **Stop `relaxed` warning about itself.** At every session start Petasos
   logs that its two risk thresholds are closer than it recommends. The
   values come from Petasos's own `relaxed` strictness. Change the values
   or the warning.
3. **Record the score with a flag.** A flag event does not say what the
   conversation's risk score was, so the record cannot show how close a
   conversation came to a block.
4. **Doctor lists directories that are not profiles.** Verbose doctor names
   `profiles/.deleted` and a retired `.git` directory among the places it
   watches, as if they were profiles.
5. **Doctor's job line is too long.** Once a job and strictness are set it
   prints five long sentences of setting descriptions under one line.

Not from the soak, and recorded elsewhere: Hermes keeps only one plugin's
note on a tool result, which matters beside `security-guidance` and Tirith
([command overlap](hermes-command-overlap.md), and host facts section 18).

## Still to test

- A block and an approval on a live install, with a person answering.
- A settings change while the gateway runs, and a worker that started
  before it.
- The optional scanners inside a working Hermes.
- The version with the fixes above: the soak ran `d519061` throughout.
