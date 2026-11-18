# Proposal: stand aside for Hermes's smart approval

Status: proposal, 2026-11-17. Not built. The owner agreed to the direction
("stand aside for the configured guardian, if any, until something sketchy
happens, then escalate") and asked for it to stay separate from the redesign
for now.

## Problem

Under `approvals.mode: smart`, which is Hermes's default and what the owner
uses, a risky terminal command in an asking job is put to a person twice, or
judged by the wrong party:

- Petasos returns Hermes's plugin `approve` directive. That request always
  reaches a person; it never reaches the guardian model.
- When Hermes's own pattern list also flags the command, Hermes then runs its
  guardian, and its own prompt if the guardian escalates.

So the guardian the operator configured never stands in for Petasos's ask, and
one command can produce two prompts. Under `manual`, Petasos already stands
aside so Hermes's prompt is the only one ([command overlap](hermes-command-overlap.md),
"Built").

## What Hermes allows

From [command overlap](hermes-command-overlap.md), "Smart approval, read
2026-11-17":

- The guardian judges only commands and `execute_code` scripts that Hermes's
  own pattern list flagged. It sees the command, Hermes's description and the
  operator's `smart_policy`. No conversation, no tool history, no plugin reason.
- A plugin's `approve` request goes to a person, never to the guardian.
- Hermes documents no plugin approval policy or auto-allow callback. Catalog
  rule 12: a plugin never routes around Hermes's approval system.

Standing aside does not route around the approval system; it hands the
decision to it. Nothing here auto-approves.

## Proposal

Petasos stands aside for a terminal command finding, writing a `deferred`
event addressed to Hermes's smart approval, when all of these hold:

1. The job's dangerous-tool posture is `approve`. A `block` posture still blocks.
2. Hermes's approval mode for this session is `smart`, after any hosted-room
   override.
3. Hermes's own pattern list flags the command, so the guardian will see it.
4. Hermes will not settle the command without a person available: not a
   hardline refusal, not a container skip, not yolo, not allowlisted, not
   already approved this session, and a person is attached. Cron,
   single-query and unattended platforms keep Petasos's decision, as today.
5. The finding is a plain command rule. Taint, personal data leaving through
   an egress sink, a degraded parameter scan and guardrail changes are never
   stood aside from, as today.
6. **Nothing sketchy has happened in the conversation**: its risk tier is
   still below `tier1` when Petasos decides.

When condition 6 fails, Petasos asks the person itself, as it does today. The
guardian cannot see the conversation, so once Petasos has seen trouble in it,
the judgment goes to someone who can weigh that. Hermes's guardian or prompt
may still follow; that second prompt is the accepted cost in this case.

Activity reads the event as "Hermes's smart approval will judge this". The
event keeps the rule and the conversation's score at the time (PET-267).

## Shape of the change

- **Host fact.** Replace the yes/no `command_will_be_asked` with an answer of
  who will judge: a person, the guardian then a person, or nobody (refused or
  granted unattended). The Hermes adapter derives it from the same calls it
  makes today, accepting `smart` as "guardian then a person". A missing,
  moved or raising detector answers nobody, so Petasos decides.
- **Decision.** `petasos/enforce/decisions.py` defers on "guardian then a
  person" only when the session tier is below `tier1`. The tier is the guard's,
  read at decision time.
- **No new settings.** The behaviour follows Hermes's own approval mode. A
  switch can be added later if an operator wants Petasos's own ask under `smart`.

## Rejected

- **Write Petasos's reason into `approvals.smart_policy`.** It is the
  operator's trusted prompt channel and Hermes alone writes its config.
  Changing it from a plugin would be the guardrail change Petasos blocks.
- **Call the approval model from Petasos** (`allow_task_override` on the
  `approval` task). That is a plugin making its own approval decision, which
  catalog rule 12 forbids, and it bypasses the operator's choice of who
  approves.
- **Stand aside under `smart` regardless of the conversation's risk.** It
  leaves a blind model to approve a command in a conversation Petasos already
  considers risky.
- **Keep today's behaviour.** It is safe but asks twice and ignores the
  operator's configured guardian.

## Risks

- **The guardian approves something Petasos would have asked about**, without
  Petasos's reason. That is the treatment Hermes gives its own detections under
  the policy the operator chose. Condition 6 limits it to conversations with no
  recorded trouble.
- **Frozen enforcement record.** The parity harness's fake Hermes reports
  `smart` (`tests/enforce_parity/hermes_adapter.py`). Steps with a terminal
  command finding under an `approve` posture could move from an approval to a
  deferral. Those must be named in `tests/enforce_parity/differences.json`,
  not re-recorded.
- **Real guardian behaviour** has not been observed, in particular on
  `execute_code` scripts. The tests below use a stand-in verdict, as the
  existing harness does.

## Tests

- Decisions: every condition above, one at a time, including a session that
  crosses `tier1` between two identical commands.
- Real Hermes, in the sandbox: under `smart` with a stand-in guardian returning
  each verdict (approve, deny, escalate), a flagged command produces exactly
  one judgment and one `deferred` event; under `manual` nothing changes; under
  cron and single-query nothing changes; at `tier1` Petasos asks.
- Measure on the stored history with `scripts/replay_history.py` before and
  after. The replay has no approvals, so expect no change in flags or blocks.

## Open

- Whether a flag below `tier1`, such as one earlier injection finding, should
  count as sketchy on its own.
- Whether the same tier rule should apply when standing aside for Tirith, which
  asks a person and so does not have the guardian's blindness.
