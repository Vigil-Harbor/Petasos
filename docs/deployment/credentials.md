# Credentials and reports

Hermes owns secret retrieval and authentication. Petasos uses the host redactor for reporting text and does not retrieve a second copy of vault contents or rewrite the arguments of an approved tool.

## Petasos secrets

`PETASOS_SESSION_SECRET` binds session tokens and signs enforcement records. Hermes stores the plugin secret in the profile's env file; Petasos expects base64. `PETASOS_HASH_KEY` supplies the key for hash-mode anonymization. Use Hermes's plugin secret fields or its env-file mechanism, outside the agent conversation. The settings API returns only whether each is set.

Library callers supply `Secrets` beside the config. Secrets are not config fields and their representation does not print values. See [library use](../usage/library.md).

## Read a redacted report carefully

Masked content does not prove a credential left the machine. An unchanged value does not certify that the text has no secrets. If host redaction is unavailable or an excerpt exceeds its budget, Petasos withholds the display text. Execution arguments remain unchanged.

Never use a credential as a session, turn or call identifier. Protect model transcripts, host logs and exported files separately; report redaction does not sanitize every destination. Signed records are not encrypted.

If disclosure is plausible, use the issuer's revocation and replacement procedure, update the host's existing secret source and verify the affected processes use the replacement. Keep raw secrets out of chat, command arguments, screenshots and issue attachments.

The [recorded credential run](evidence/pet250-hermes-5019bf7067.json) is evidence for its stated host and runtime. It is not verification of this install or a live secret-manager account. Use `petasos doctor` for current install diagnostics and the host's own workflow for credential rotation.
