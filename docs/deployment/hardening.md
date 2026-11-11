# Deployment hardening

Petasos detects and enforces policy at tool boundaries. It cannot contain an agent that has unrestricted access to the operating system or network. Pair it with account separation, filesystem permissions and network controls.

## Before unattended work

- Check the intended profile with `petasos doctor` and read every warning. A report describes the install and the current check, not every running process.
- Review [jobs and strictness](../usage/jobs-and-strictness.md), overrides and [scanner setup](../usage/scanners.md). Verify model availability instead of assuming installed packages provide working checks.
- Review [guardrail integrity](../usage/guardrail-integrity.md). Recognition can miss disguised writes. A pin fixes settings and plugin lists across profiles, with the limits described there.
- Keep every profile's settings, secrets, plugin files and Python environment out of the agent's writable scope. A relaxed setting staged in another profile can take effect when that profile is used.
- Restrict shell and file access with operating-system isolation. Restrict network destinations separately from tool classification.
- Protect the dashboard's authenticated session from the agent's shell and HTTP tools. Loopback alone does not separate processes in the same account.

## Data and evidence

Petasos scans tool calls and tool results. It does not intercept model requests or every possible network path. For sensitive source data, review [egress limits](banking-egress.md) and choose where inference runs.

Set secrets through Hermes's plugin secret fields or its profile env-file mechanism; see [credentials](credentials.md). A signature can show that a record was not altered under the signing key. It does not encrypt the record, prove that no entry was deleted, or protect against a writer holding the key. Protect the event spool and its rotated sibling with permissions and retention controls.

Try it uses a private trial and does not run a tool or change a conversation's risk. Use it for representative inputs, then verify the intended host workflow separately. The [host evidence](../architecture/hermes-host-facts.md) states what was exercised and what remains unverified; no live gateway or kanban-worker proof is claimed.
