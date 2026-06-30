# Per-Hermes-agent security profiles

One Petasos install can enforce a different security posture for each Hermes
agent role. A coding agent, a customer-service agent, and a research agent can
each run their own Petasos config out of one plugin, and the Config Editor's
**Hermes agent profile selector** is how you view and edit each one.

This page is the usage walkthrough. For the deployment and restart contract see
[hermes-desktop.md](../deployment/hermes-desktop.md); for the per-field reference
see [configuration.md](configuration.md).

## Two different "profiles" (do not conflate them)

There are two independent axes, and the editor surfaces both:

- **The Hermes agent profile** is *which agent role you are configuring*, i.e.
  which `config.yaml` on disk you are editing (for example
  `~/AppData/Local/hermes/profiles/gibson/config.yaml`). This is the selector at
  the very top of the Config Editor, above the Strength dial.
- **The internal Petasos profile** (`profile_name`, the editor's section 1
  "Profiles": `general`, `code_generation`, `customer_service`, `research`,
  `admin`) is a *strength preset* applied within whichever config you are
  editing.

So you pick the **agent role** with the top selector, then tune that role's
posture (including its `profile_name`) underneath. Each agent role keeps its own
config; changing one never touches another.

## Where it is

The selector sits at the top of the **Config Editor** tab, above the Strength
dial. Under it, a binding read-out names exactly what you are editing:

```text
binding: gibson · tier profile · ~\AppData\Local\hermes\profiles\gibson
```

`tier` is `profile` (a `profiles/<name>/config.yaml`), `hermes_home`
(`HERMES_HOME`), or `root` (the legacy root config). The path is shown
home-collapsed (`~`) so it never carries your OS username into the UI or a
screenshot.

## Two modes

Which mode you get depends on whether your Hermes build hands Petasos a profile
binding signal. You do not configure this; you can tell by looking:

- **Editable selector (in-house).** The selector is a dropdown you can change.
  Use it when the host does not drive the profile for you. The equipped profile
  is labelled `(equipped)`.
- **Diegetic / read-only.** The selector shows the host-bound profile name with
  no dropdown, plus the note "This profile follows the Hermes sidebar selection."
  Here Petasos follows the host: switch the agent profile in Hermes itself and
  the editor reflects it.

## Editing: equipped vs non-equipped

The selector lets you edit *any* of your Hermes profiles, not just the running
one, and the save behaviour differs:

- **The equipped profile** (`(equipped)`): edits **hot-apply** on save. This is
  the live config the running gateway enforces.
- **A non-equipped profile**: edits **persist to that profile's `config.yaml`
  only**, and the editor shows the pinned banner: *"This isn't the equipped
  profile; changes take effect when it's equipped (restart)."* Use this to
  pre-stage a role you are about to switch to.

Because a non-equipped edit is staged on disk, it becomes live the moment that
profile is equipped. Treat every profile home as a security surface and keep it
out of the agent's reach (see the multi-home boundary in
[hardening.md](../deployment/hardening.md) section 6).

## Switching profiles with unsaved edits

Changing the selected profile while the form has unsaved edits is gated. The
first change shows a confirm strip ("Switching profiles discards your N unsaved
edits. Choose <name> again to confirm.") and reverts the dropdown; choosing the
same target a second time confirms the switch and discards the pending edits.
This keeps a stray click from silently throwing away work.

## The "effective (what's enforced)" disclosure

Below the selector is a collapsed **effective (what's enforced)** disclosure.
Expand it to see the resolved tier thresholds plus anything the active internal
profile adds (confidence floor, suppressed rules, severity overrides, extra PII
entities) that is not a plain config field. It is collapsed by default so it
does not crowd the Strength view; the detail is one click away when you need to
audit exactly what the resolved posture is.

## What applies live vs what needs a restart

Editing the **equipped** profile's settings hot-applies on save: the running
gateway re-reads its pinned config and the new values take effect on the next
tool call. No restart is needed for that.

What does **not** apply live is changing *which* profile is equipped. Petasos
pins its config binding once, at boot, so retargeting a running gateway to a
different profile in place is not picked up. Edits you stage on a **non-equipped**
profile stay dormant until that profile is equipped, and on current Hermes
equipping it means a **gateway/process restart**. After switching a
security-bearing agent's profile, restart its gateway and confirm the new binding
from the `PETASOS_ARMED_RESOLUTION tier=<t> path=<p>` log line. Full contract:
[hardening.md](../deployment/hardening.md) section 6.

---

*Reflects the Config Editor as of Petasos 0.2.0.*
