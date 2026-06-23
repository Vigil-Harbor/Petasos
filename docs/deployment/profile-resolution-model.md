# Petasos profile-resolution model (the two profile axes)

Petasos has **two independent things both called a "profile."** Conflating them
is the single most common source of confusion when reasoning about where a
posture setting lives and what changes it. PET-146 added the Config Editor's
Hermes-agent-profile selector, which makes the distinction operator-visible, so
this page pins it down.

## Axis 1 — the Hermes profile home (which `config.yaml`)

A *Hermes profile home* is a directory on disk that holds a `config.yaml` with a
`petasos:` section. Hermes 0.16+ runs each persona as a separate profile home
under `profiles/<name>/`. The effective file is resolved by
`petasos/console/_paths.py::resolve_hermes_config_path()` with this precedence:

1. **`HERMES_HOME` env** (tier `hermes_home`) — `$HERMES_HOME/config.yaml`.
2. **active-profile pointer** (tier `profile`) — `<root>/profiles/<name>/config.yaml`,
   where `<name>` is read from `<root>/active_profile`.
3. **v0.15 root** (tier `root`) — `<root>/config.yaml`. If the `active_profile`
   pointer names a missing directory, resolution falls back to root and carries a
   **dangling-pointer warning** (surfaced in the editor as a banner labeled as the
   *active* binding).

`<root>` is the Hermes root:

- **Windows:** `%LOCALAPPDATA%\hermes` (e.g. `C:\Users\<you>\AppData\Local\hermes`),
  with profiles at `%LOCALAPPDATA%\hermes\profiles\<name>\config.yaml`.
- **POSIX:** `~/.hermes`, with profiles at `~/.hermes/profiles/<name>/config.yaml`.

`list_hermes_profiles()` enumerates `profiles/*/config.yaml` for the selector;
`resolve_profile_config_path(name)` resolves one named member (traversal-guarded).

Every `petasos:` posture field lives **inside one of these `config.yaml` files**
and is therefore **per-Hermes-profile**. This includes the three safety levers
that an earlier draft proposed treating as machine-global:

- `fail_mode`
- `source_taint_namespaces` (PET-134 egress fence)
- `egress_sink_tools` (PET-112 egress PII gate)

There is **no machine-global tier.** Editing any of these under profile *X*
writes to *X*'s `config.yaml` and leaves every other profile untouched. The
editor states this plainly ("scoped to the selected Hermes profile") and prints
no "global" marker; the `scope` metadata key on every field is `"profile"`
(`_config_meta.generate_config_metadata`), locking the disclosure contract.

## Axis 2 — the internal `profile_name` (a runtime tuning overlay)

The `petasos.profile_name` field selects an *internal* `ResolvedProfile`
(`petasos/session/profiles/`), one of five built-ins (`general`,
`customer_service`, `code_generation`, `research`, `admin`) or a custom dict.
This is **not** a directory and **not** a `config.yaml`. It is a runtime overlay
the pipeline consults field-by-field at scan time. What it contributes:

- `tier_thresholds` — the **only config-shaped** runtime override; when set it
  replaces `config.{tier1,tier2,tier3}_threshold` in `guard._state_to_tier`. This
  is why the editor's "effective (what's enforced)" read-out overlays the
  profile's tier thresholds onto the raw config values.
- `confidence_floor` — a **live scan-time** override that drops findings below the
  floor (`pipeline.py`, Stage 5b). It is *not* a `PetasosConfig` field, so it
  never appears in `effective_config`; the editor surfaces it under
  `active_profile_overrides` so the finding-dropping floor stays visible.
- `suppress_rules`, `severity_overrides`, `pii_entities_extra`,
  `tool_exempt_list`, `tool_alias_map` — non-config-shaped effects, also surfaced
  under `active_profile_overrides`.

### Effective view = config ⊕ internal-profile overrides

The pipeline holds no single merged config; it consults the active
`ResolvedProfile` at runtime. The Config Editor reconstructs an **effective
view** that matches enforcement: `config.to_dict()` with the tier thresholds
overlaid from the active internal profile when present. Nothing else is overlaid,
because nothing else is a config-shaped runtime override.

## The two axes do not interact

The Hermes profile home decides **which file** you are reading and writing. The
internal `profile_name` (a field *inside* that file) decides the **runtime
overlay** applied when that file is the equipped one. Switching the selector
changes the file (axis 1); changing `profile_name` changes the overlay (axis 2).

## Equipped vs non-equipped edits

- **Equipped profile** (the live binding): editing hot-applies through the
  existing `Pipeline.reconfigure()` path (PET-126) and persists to its
  `config.yaml`.
- **Non-equipped profile**: editing persists to **that profile's** `config.yaml`
  only and shows a restart banner — the change takes effect when the profile is
  equipped (restart). PET-146 deliberately does not trigger a live equip-swap from
  the selector; a trusted live re-bind is PET-147's `on_profile_change` signal.

## Hardening consequence — all profile homes, not just the active one

The selector enumerates and edits **every** `profiles/*/config.yaml`. A
per-profile egress fence (`source_taint_namespaces`) or a relaxed `fail_mode` can
therefore be **pre-staged in a non-equipped profile** and arm on the next equip.
The self-disarm / self-tamper mitigation in
[`hardening.md` §6](./hardening.md#6-protect-petasoss-own-config-self-disarm--self-tamper)
must extend to **all** profile homes (every `profiles/*/config.yaml` plus the
v0.15 root and any `$HERMES_HOME`), not only the active one: a read-only mount or
write-denying ACL that covers just the equipped profile leaves the pre-stage
vector open. Treat the whole `profiles/` tree as security-bearing.
