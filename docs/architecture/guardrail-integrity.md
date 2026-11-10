# Guardrail integrity

Status: design, agreed in principle 2026-11-10. Built as package S1, after the
Hermes adapter (C2a). Supersedes the "self-protection" notes in section 7.4 of
`redesign.md`.

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
- **No standing approval.** Hermes offers "always", which writes a permanent
  allow-list entry. For guardrail changes Petasos does not honour it: the
  approval rule key carries the session, so a permanent entry cannot match
  any other session, and it lapses with the time limit like any session
  approval.
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
with what changed and, when it followed an approved self-change, which
approval. A change the operator did not make is then visible in the console
and to `doctor`, whichever way it got in.

## What changes in the code

- **Config.** `tools.self_change` and `tools.self_change_minutes`; `support`
  sets `never`.
- **Guard.** Recognise the commands and paths listed above, in addition to
  today's config-file paths. The host supplies the paths (the Hermes adapter
  already does for the files); the command patterns are Hermes-specific and
  are supplied by the adapter too, so the guard stays host-agnostic.
- **Enforcer.** A recognised guardrail change is decided before the rest of
  the ladder: blocked under `never`; under `approve`, held for approval unless
  a live session approval covers it, and blocked when no person can be asked.
- **Hermes adapter.** Session-carrying rule keys for these approvals; reports
  whether a person is attached.
- **Command line.** `pin`, `unpin`, and the state in `doctor`.

## Behaviour change

This is a deliberate change from 0.5, where a guardrail write is allowed
below tier 2. The parity records for self-modification cases are re-recorded
in the commit that makes it, and the changelog names it as breaking.
