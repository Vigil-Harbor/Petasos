# Draft decision: one settings tree and native Hermes enforcement

Status: draft for the owner to place in the private wiki. The private wiki was not opened. This records the [redesign contract](redesign.md), especially sections 13 and 14; it does not claim a merge or release.

## Decision

Petasos owns one immutable, validated settings tree. A job (`role`) and strictness (`level`) set disjoint fields; explicit overrides sit above both. The schema declares labels, help, choices, bounds and restart requirements. Settings forms and generated reference documentation derive from those declarations. Lists replace the lists beneath them; no additive layer syntax is provided.

The scanner registry is the single config-to-scanner construction path. A host-neutral `Enforcer` owns lifecycle, tool-call decisions, approvals and records. The Hermes adapter translates hooks and host facts, and uses Hermes's settings writer, redactor and approval prompt. The wheel owns behaviour; the directory plugin supplies the manifest and dashboard assets. The Petasos tab replaces the standalone console and its token. Documentation generation is checked by regeneration and comparison, not marker comments.

The stable library imports are the root API in section 9 of the contract. The library remains usable without Hermes. Frozen parity records preserve the tested behaviour; deliberate enforcement differences are recorded separately.

## Supersedes

When placing this decision, add back-links to these four decisions named in section 13 of the contract:

| Decision | Replacement |
|---|---|
| 2026-06-14: strength-preset registry separate from `profile_name` | One settings tree with job, strictness and overrides. |
| 2026-06-17: reference plugin as a hand-synced deployment artefact | Wheel-owned enforcement and a directory plugin installed and checked by commands. |
| 2026-06-23: retire inert settings from the editor but keep the field | Delete settings that do not affect behaviour; derive the editable reference from the schema. |
| 2026-09-06: config builder in the plugin because of version skew | Registry composition in the library; the plugin imports wheel-owned behaviour. |

The earlier decision files and their exact wiki paths were not inspected. The owner must attach the back-links when placing this draft.

## Owner decisions

Section 14 records these settled decisions on 2026-11-11:

- Credits and donation wording from the console's About page belong in the README footer, not the tab. The owner proofreads the README before it is called done.
- A list in a layer or override replaces the list beneath it. There is no additive form for now.
- Semgrep cannot be enabled inside Hermes without engine lifecycle ownership. The form offers only Never; saves that leave it requested and scanner-add are refused. A hand-written request remains an unavailable check and follows failure policy. One host seam answers whether it can run.
- There is no compatibility route for the 0.18 Hermes fork.
- Two switches remain: Hermes decides whether Petasos loads, and Petasos's `enabled` pauses checks. The tab offers Pause; doctor and the tab explain which switch is off.
- A pin covers complete Petasos settings, both plugin lists and the effective hook timeout. Hermes pins each plugin list as one value, so plugin selection as a whole is fixed until unpinning. The command discloses that before writing.

## Scope and limits

Ordinary settings belong to a Hermes profile. A managed pin applies to every profile using its managed directory; it is not profile-local. Petasos reads its recorded pin whole to avoid Hermes overlay gaps for mapping entries and unset values. A pin does not protect plugin files, Python or evidence, prevent safe mode, or stop an account redirecting the managed directory. Recognition alone can miss disguised guardrail writes.

The design retains atomic live application, centralized scanner construction and classic scripts without a bundler. Section 13 says the console/operator and optional-auth decision stands, while section 8 retires the standalone console and uses Hermes's authentication. The owner should reconcile that design-record wording when placing this draft; this draft follows the built host surface and does not carry forward a standalone token.

Live gateway settings refresh, kanban-worker behaviour, cheaper live application for some Presidio fields, and visual polish remain open in the design record. Recorded sandbox checks are evidence for their stated paths, not proof of a live deployment. See [host facts](hermes-host-facts.md) and [guardrail integrity](guardrail-integrity.md).
