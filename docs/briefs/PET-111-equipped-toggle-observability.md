# PET-111: Equipped/Unequipped master toggle on Observability tab (live arm/disarm)

> Plane: PET-111 (Todo). Console work — intersects the standing **PET-13**
> umbrella but is **not** a child of it. Pair with `/spec-cycle` → `/ship-spec`.

## Problem

The Petasos console exposes per-feature toggles (`tool_guard_enabled`,
`frequency_enabled`, …) in the Config Editor, but there is **no one-click
master switch**. The actual "is Petasos enforcing anything?" gate is the
plugin-level key `petasos.enabled` in `config.yaml`, which:

- is read **once at plugin init** — `reference_plugin/__init__.py:158`
  (`enabled = raw_config.pop("enabled", True)`); when false the plugin sets
  `_init_error = "disabled"` and **never builds the pipeline** (`:160`-`:163`),
  and `_pre_tool_call` short-circuits to pass-through at `:445`-`:446`;
- is **not** a `PetasosConfig` field (`config.py` has no `enabled`) — so the
  Config Editor never renders it and `update_config` never round-trips it.

Operators want an obvious **Equipped / Unequipped** switch on the Observability
tab (tab 1, `obs` — default-active per `petasos.js:1117`-`1121`) that arms or
disarms **all** enforcement, and — per the decision below — does so for
sessions that are **already running**, not just new ones.

## Decisions (locked with user)

1. **Scope = master gate.** The switch controls `petasos.enabled`. Unequipped =
   zero enforcement (no syntactic scan, no ML scanners, no tool-call guard, no
   audit, no alerting). Equipped = normal enforcement per the rest of config.
2. **Live effect required.** Toggling must change behavior in an
   already-running session by its **next tool call** — not only in new
   sessions. (User explicitly chose "Master + live effect" over new-session-only.)
3. **Placement.** A prominent toggle at the top of the Observability tab,
   styled with the existing `.switch` pill component (`petasos.css`; PET-89
   fixed its pill shape). Reflects current armed state on load.
4. **Re-arm strategy = Option A** (always build the pipeline at init regardless
   of `enabled`; enforcement decided solely by the per-call `_is_armed()`
   check). Chosen over lazy-build so a re-arm mid-incident pays no cold-start
   penalty. User-confirmed 2026-06-14.

## The hard part: live arm/disarm across two processes

The console **dashboard** and the agent **gateway** are separate OS processes
(`plugin_api.py` self-inits its own Pipeline for exactly this reason), and
Hermes snapshots config at session start (footgun #3). So an in-memory flag in
the dashboard cannot reach the running gateway. The arm state must travel
**through a file** the gateway re-reads on its hot path.

### Source of truth

`petasos.enabled` in the resolved `config.yaml`
(via `petasos/console/_paths.py:resolve_hermes_config_path()` +
`read_petasos_section()` — already the path the plugin and dashboard agree on).
No second source of truth / no separate marker file (avoids drift).

### Gateway side — re-read on the hot path (proposed)

Add an `_is_armed()` helper consulted at the **top of** `_pre_tool_call` (and
`_post_tool_call`) in the reference plugin, replacing the init-time-only gate:

- `os.stat()` the resolved config path; if `st_mtime` is unchanged since last
  read, return the **cached** boolean (steady-state cost = one `stat`, no YAML
  parse);
- on mtime change, re-parse just the `petasos.enabled` key and update the cache;
- **fail-secure:** any stat/parse error returns `True` (armed). A transient
  file-read race must never silently disarm a security control. (Note this
  matches the existing `enabled` default of `True`.)

**Re-arm (off→on) — LOCKED to Option A.** Today a boot with `enabled: false`
never builds the pipeline, so flipping on at runtime would have nothing to
enforce with. The decision (Decision 4) is:

- **Always build, gate per call.** Build the pipeline at init regardless of
  `enabled`; enforcement is decided solely by `_is_armed()` per call. Symmetric
  arm/disarm, predictable latency. Replace the `_init_error = "disabled"`
  early-return (`reference_plugin/__init__.py:160-163`) with an `_armed`-gated
  path that still builds `_pipeline`/`_guard`. Cost accepted: scanners load at
  boot even when starting disarmed (~startup time / memory) — acceptable for a
  control that must re-arm without a cold-start penalty at the moment it matters.

Rejected alternative (B): lazy-build on first arm — cheaper disarmed boot, but a
first-call latency spike and extra state. Not chosen.

### Dashboard side — write the key atomically

A new write path sets **only** `petasos.enabled` in `config.yaml`:
read-modify-write the full YAML, flip the one key, atomic write (tempfile +
`os.replace`, the pattern already in `server.py` / `plugin_api.py`
`_persist_config`). It must **not** go through `PetasosConfig` (the key isn't a
field) and must preserve every other key.

**Config Editor clobber guard (regression risk).** `update_config` persists the
`petasos:` section from a validated `PetasosConfig`. Since `enabled` is not a
field, a naive section rewrite would **drop** it on the next Config Editor save
(same failure class as the footgun #2 model-switcher key-wipe). The persist path
must read the existing section and **merge**, preserving `enabled` (and any
other non-`PetasosConfig` keys).

## Scope

### Backend — `petasos/console/`

New endpoints (mirror on both surfaces, as every other route is):

| Endpoint | Method | Behavior |
|---|---|---|
| `/armed` | GET | `{ "armed": bool }` — current `petasos.enabled` from resolved config |
| `/armed` | POST | body `{ "armed": bool }` → atomic-write the key, return new state |

- `server.py` (standalone, `127.0.0.1:8384`) and `hermes/plugin_api.py`
  (embedded) both delegate to a shared handler (the established pattern).
- Optionally broadcast an `armed` SSE event over the existing `_sse.py`
  broadcaster so multiple open console tabs stay in sync (nice-to-have; the obs
  tab already re-renders on SSE).

### Reference plugin — `reference_plugin/__init__.py`

- `_is_armed()` mtime-cached reader (above), fail-secure True.
- Hot-path gate at the top of `_pre_tool_call`/`_post_tool_call`.
- Init change per option (A)/(B) from `/spec-cycle`.

### Frontend — `petasos/console/static/petasos.js` + `petasos.css`

- In `Pet.renderDashboard` (`:578`), add an **Equipped/Unequipped** `.switch`
  at the top of the obs tab with a clear label and helmet-state affordance
  (armed = active/green, disarmed = muted/grey). `Pet.HelpTip` explains live vs
  next-tool-call semantics.
- On mount: `GET /armed` → set switch. On toggle: optimistic flip → `POST
  /armed` → revert + inline error on failure (reuse the existing
  `{field,message}` error rendering). **No `innerHTML`** — use `Pet.h` /
  `Pet.richText` (PET-82 posture; the richtext `#19` tripwire still applies).
- CSS: reuse `.switch`; add only an armed/disarmed color state.

## Acceptance criteria

- Observability tab shows the switch reflecting current `petasos.enabled` on load.
- Disarm stops enforcement in a **running** session by the next tool call; re-arm
  resumes it (verified against `_pre_tool_call`).
- State persists to `config.yaml`; **new** sessions honor it; a subsequent Config
  Editor save does **not** wipe `enabled`.
- Steady-state hot-path cost is one `stat` (no full YAML parse per call).
- Pipeline never throws; `_is_armed()` fails secure (armed) on read error;
  disarmed = explicit operator pass-through (distinct from a fail-mode bypass).

## Test standards

- Unit: `_is_armed()` mtime-cache hit/miss + fail-secure-on-error; persist path
  flips only `enabled` and preserves siblings; Config-Editor-save preserves
  `enabled`.
- Behavior: disarm short-circuits before `guard.evaluate`; re-arm enforces
  (option A: pipeline present; option B: lazy build occurs once).
- Endpoint: GET/POST `/armed` on both `server.py` and `plugin_api.py`,
  validation (non-bool body → 422 `{field,message}`).
- Frontend: switch renders on obs, calls GET on mount and POST on toggle,
  reverts on failure, uses no `innerHTML`.

## Risks / watch-list

- **Windows file-lock during atomic write** while the gateway reads (footgun
  #11): reader tolerates transient failure (fail-secure armed); writer uses
  atomic replace.
- **Concurrent writers** (dashboard `/armed` vs UI model-switcher rewriting
  config): atomic replace bounds corruption to last-writer-wins; `petasos:` is a
  top-level key the model switcher leaves intact (footgun #2).
- **Boot cost** if option (A) loads scanners while disarmed — acceptable for a
  re-armable security control; call out in the spec.

## Out of scope

- Per-feature toggles (already in the Config Editor).
- Changing `fail_mode` semantics or the Tier-3 floor.
- Any licensing/keyed gating (all features remain free).
