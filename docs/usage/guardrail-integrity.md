# Guardrail integrity

Guardrail integrity says whether the agent can change the settings that protect it. Doctor and Overview report the state. The setting is `tools.self_change`; its choices and the session approval duration are in the [settings reference](../reference/settings.md).

## Open

The agent can change a recognized guardrail only with a fresh approval from a person. A one-call approval covers that call. A session approval expires after the configured duration or when the session ends. It does not carry into another conversation. A standing Hermes approval does not grant future guardrail changes: Petasos gives later requests new keys. If the host would approve without asking a person, Petasos blocks the change.

## Blocked

Recognized guardrail changes from the conversation are refused. You can still change settings outside the agent, in your terminal or the settings form. Recognition reads tool names, paths and command text; a disguised shell write can evade it. Blocked is a policy enforced by detection, not an operating-system barrier.

## Pinned

A pin fixes the complete Petasos settings, both Hermes plugin lists and the effective plugin-check timeout in Hermes's managed configuration. Petasos reads the pinned settings whole instead of merging in profile values. A protected pin file and directory require administrator access to change. The settings form and Petasos settings commands refuse profile writes while that pin is in force.

**A pin applies to every profile on the machine using that managed directory.** The profile used to take the snapshot does not limit its scope. Both plugin lists are fixed as whole lists, so no plugin can be enabled or disabled by profile settings while the pin is in force.

Run `petasos hermes pin` to preview the values and scope. With `--write`, the command either replaces an already writable managed file or prepares a private merged document and prints system commands for an administrator to review and run. Never run Petasos or Python with administrator rights. Run `petasos doctor` afterwards.

`petasos hermes unpin` previews removal. It shows profile differences that would take effect and refuses removal until you explicitly accept them. Review those differences before using `--accept-profile-changes --write`.

## Read the limits

A pin does not protect plugin files, the Python environment or the event record. It does not stop safe mode. An account that can redirect `HERMES_MANAGED_DIR` can bypass the managed directory. Keep those surfaces outside the agent's control with operating-system permissions and isolation.

Doctor distinguishes a full pin from a partial pin, a writable pin, a pin not in force and a changed profile. A writable pin does not protect settings from the same account. A manually written managed file without Petasos's pin record can leave mapping entries and unset values open. Do not treat those states as pinned protection.

The [design and isolated evidence](../architecture/guardrail-integrity.md) record the tested limits. Administrator ownership and native Windows pinning were not exercised. See [deployment hardening](../deployment/hardening.md) for the surrounding controls.
