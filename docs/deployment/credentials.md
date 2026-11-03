# Hermes credentials and Petasos reports

Hermes owns secret retrieval, authentication and credential use. Petasos reuses
Hermes's redactor for approval excerpts, stored approval commands/descriptions
and enforcement reasons. It does not retrieve vault contents or change the
arguments passed to an approved tool.

This integration is grounded against Hermes checkout `5019bf7067`. Check the
installed CLI's help before applying commands to a different host version.

## Password-manager setup

For API credentials, use Hermes's external secret sources. Its 1Password source
resolves configured `op://vault/item/field` references using the installed,
authenticated `op` CLI. Its Bitwarden source uses Bitwarden Secrets Manager;
this is distinct from the browser-login vault. Start with the host's own setup
and status commands:

```text
hermes secrets onepassword setup
hermes secrets onepassword status
hermes secrets bitwarden setup
hermes secrets bitwarden status
```

Run the applicable commands in the intended Hermes profile. Use the interactive
masked prompt for bootstrap tokens. Do not place credential values in shell
arguments, chat, screenshots, a Petasos profile, or an issue attachment. For
1Password, map an environment variable to a reference with
`hermes secrets onepassword set NAME op://vault/item/field`; the reference is
metadata, not the credential value. Keep private vault/item names private too.

For browser logins, use Hermes's browser-vault facilities. That path registers
exact values with the host's profile-scoped redactor before filling. Petasos
uses the active host context for every redaction call; it does not collect a
second process-wide list of credentials.

Keep Hermes's `security.redact_secrets` enabled for its general logs and tool
outputs. Petasos forces redaction independently on the reporting fields named
above, including when that host preference is disabled. This does not add a
universal secrets scanner or guarantee detection of arbitrary unknown passwords.
The host's exact-value registry and credential-pattern coverage still apply.

## What the notices mean

**Sensitive content masked locally; exposure unconfirmed.** The redactor changed
text before Petasos stored or displayed it. The approval prompt can show this
notice to the model/operator, and the approval history and refused queue show
the stored record's redaction status. This is not evidence that the tool ran or
that a credential left the machine. Review the approval outcome and destination
before deciding whether rotation is necessary.

**Sensitive display withheld; redaction unavailable.** Petasos could not safely
redact a field, or the field exceeded its input budget. It stores a fixed
placeholder and preserves the approval outcome. Verify that the plugin/library
copies and Hermes version are compatible. Do not work around this by copying
the raw value into the approval description or a bug report.

An `unchanged` status means the redactor made no change. It does not certify
that the text contains no secrets. Older records have no status; their absence
is not evidence that redaction ran. An already-redacted host value may also be
unchanged at the Petasos boundary.

Commands and descriptions are redacted before their display caps are applied,
so truncation does not destroy an exact-value match. Nested tool-argument strings
are redacted before JSON escaping. Unsupported, oversized or deeply nested
excerpt inputs are withheld. Correlation identifiers (session/turn/call IDs and
rule keys) retain their original semantics; never use a credential as an ID.

## Exposure triage and rotation

1. Identify the affected profile, credential issuer, approval outcome, time and
   destination. Record identifiers and redacted evidence only. Local masking
   alone is not confirmed exposure. A reusable value in a destination's log,
   published artifact, remote request or unauthorized recipient is stronger
   evidence; treat plausible unauthorized disclosure as a rotation decision.
2. Pause affected unattended jobs through the host/operator controls while
   investigating. A review mark in the refused queue does not revoke a key,
   change an approval policy or rerun a refused command.
3. Revoke the affected credential at its issuer and issue a replacement with the
   required minimum permissions. Changing a vault entry alone does not revoke
   the old issuer credential. For a compromised secret-manager bootstrap token,
   revoke and replace that token through the manager's own controls too.
4. Update the existing vault field/reference or the host's configured mapping.
   Hermes provides interactive `hermes secrets onepassword token` and
   `hermes secrets bitwarden token` flows for their bootstrap tokens. Use the
   masked prompt; do not pass the new token on the command line.
5. Refresh the affected host processes under the normal deployment procedure.
   External sources resolve at startup and may cache values; editing the vault
   does not prove a running gateway has discarded its old value. Check the
   installed source's cache/status behavior and restart only the intended jobs.
6. Make a harmless authenticated request through the intended tool and profile.
   Verify that the new credential works and the old one is revoked without
   printing either. Confirm sibling profiles retain their own identities.
7. Inspect relevant local logs, history segments, exported artifacts, shared
   messages and downstream systems for copies. Do not paste raw evidence into
   chat or upload logs for convenience. Apply the operator's retention and
   incident procedure; preserve required evidence and access controls.
8. Record the rotation time, issuer credential identifier, scope and verification
   outcome. Resume the affected work only after the replacement is verified.

## Verification and limits

The regression suite uses synthetic secrets and the actual spool/history
writers. A separate local compatibility probe exercises the real Hermes
redactor. Neither proves a live 1Password/Bitwarden account is configured or
that an unattended host has loaded a replacement token. Validate those through
the operator's host workflow, without sharing credentials with the coding agent.

This change protects newly written approval text and enforcement reasons.
It does not rewrite legacy history, sanitize arbitrary third-party log handlers,
or change the standalone console playground's input/result contract. Host logs,
model transcripts, downstream tool output and exported files need their own
redaction and access-control policies. Scan finding metadata omits matched text,
but custom scanner messages and errors are not a universal safe-data guarantee.

The spool and history are HMAC-signed JSONL, not encrypted storage. Signature
verification proves integrity under the configured key, not confidentiality or
absence of credentials. Encrypted report exports are tracked separately as
PET-253 and do not block this first credentials milestone. Raw-secret collection
is not a prerequisite for that follow-up.
