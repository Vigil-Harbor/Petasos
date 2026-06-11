# Petasos Console — Frontend Hand-off

> **Status:** DRAFT — 2026-05-30
> **Audience:** Frontend implementor building the vanilla HTML/JS console SPA
> **Canonical contract:** [`petasos-console-api.yaml`](petasos-console-api.yaml) (OpenAPI 3.1)
> **Parent spec:** [`petasos-console-spec.md`](../../petasos-console-spec.md)

This document carries the narrative the OpenAPI spec can't hold: auth model, real-time data flow, the OSS/Premium rendering boundary, session semantics, error conventions, and embedding constraints. **Do not duplicate schemas here** — the YAML is the source of truth for field names, types, and constraints.

---

## 1. Architecture at a Glance

The Console is a single-page vanilla HTML/JS/CSS app served as static package data by a FastAPI backend running in-process alongside the Petasos Pipeline. No React, no npm, no build step. The frontend talks to seven REST endpoints and one SSE stream, all on `127.0.0.1:{port}`.

```
Browser ──┬── GET/PUT /api/config     (Config Editor)
          ├── POST    /api/scan       (Playground)
          ├── GET     /api/health     (Dashboard)
          ├── GET     /api/scan-history (Dashboard)
          ├── GET     /api/profiles   (Config Editor / Dashboard)
          ├── POST    /api/activate   (Premium CTA)
          ├── POST    /api/deactivate (Premium CTA)
          └── GET     /api/events     (SSE → Dashboard)
```

No authentication. No CORS. The server binds `127.0.0.1` only — it's a local dev/ops tool. If the server isn't running, the page isn't reachable.

---

## 2. The Three Surfaces

### Config Editor (OSS)

Renders an interactive form from the field metadata returned by `GET /api/config`. The response includes both the current config values and an ordered `fields` array with type hints, defaults, descriptions, tier tags, section groupings, and validation constraints. **Generate the form from this metadata** — don't hardcode field lists. When new config fields ship, the editor picks them up automatically.

Sections: normalization, scanning, fail_mode, anonymization, frequency, escalation, profiles, tool_guard, audit, alerting, session.

Premium sections (frequency through alerting) render fully but with fields disabled and an activation CTA when `premium_features[feature]` is `"locked"`. When `"available"`, fields are editable. When `"disabled"`, the feature is licensed but the user has toggled it off — render as editable.

On successful `PUT /api/config`, display a session-restart notice: *"Changes apply to new sessions. Restart your agent session to pick up this config."* This is a hard requirement from the Hermes Desktop session boundary constraint.

### Scan Playground (OSS)

Three inputs: text area, direction toggle (`inbound`/`outbound`), optional session ID. Submit → `POST /api/scan` → render the `PipelineResult`:

- **Normalized diff:** Compare `text` (raw input) against the normalized text. The backend doesn't currently return the normalized text separately in PipelineResult — you'll need to compute a character-level diff client-side or the backend can be extended to include `normalized_text` in the response. Flag this as an open item.
- **Per-scanner findings:** Group by `scanner_results[].scanner_name`. Show each scanner's finding count, duration, and error state.
- **Merged findings:** The top-level `findings` array. Show rule_id, severity badge, confidence, message, matched_text (with position highlighting if the text is short enough).
- **Anonymized output:** If `sanitized_content` is non-null, show it.
- **Pipeline metadata:** Total latency (sum of per-scanner durations is approximate — wall-clock time from request/response is more accurate), fail-mode status, error list.
- **Premium overlay (when available):** `session_score`, `escalation_tier`, active profile name.

### Observability Dashboard (split)

**OSS tier:**

- **Scan history** — `GET /api/scan-history?limit=100`. Table: timestamp, direction, safe/blocked badge, finding count, latency. Auto-refresh via polling (10s interval) or SSE `scan_result` events.
- **Scanner health** — `GET /api/health`. Per-scanner card: name, status badge (healthy/degraded/circuit_open/unavailable), last latency, consecutive timeout count. Auto-refresh via polling.

**Premium tier (render disabled+CTA when locked):**

- **Audit log viewer** — SSE `audit` events. Filterable by session_id, severity, event_type. The `AuditPayload` shape varies by `audit_verbosity` config (minimal/standard/verbose) — render what's present, don't crash on missing fields.
- **Alert feed** — SSE `alert` events. Show rule_id, severity, message, session_id, timestamp. The `context` object is rule-specific — render as a collapsed JSON detail view.
- **Escalation timeline** — Derived from audit events that include `escalation_tier` and `session_score` in their payload (standard+ verbosity). Plot session score over time, mark tier boundaries.
- **Frequency heatmap** — Derived from audit events. Grid of sessions × time, colored by score. This requires accumulating events client-side.
- **Session inspector** — Click a session_id anywhere to drill in. Filter scan history + audit log + alert feed to that session.

---

## 3. Premium Rendering Rules

The `premium_features` manifest is the single source of truth. It appears in `PipelineResult`, `GET /api/health`, and `POST /api/activate` responses. The manifest maps feature names to one of three states:

| State | Meaning | Frontend behavior |
|---|---|---|
| `locked` | No valid license | Render section visible but disabled. Show activation CTA. |
| `disabled` | Licensed but user toggled off | Render as editable (user can toggle on). No CTA. |
| `available` | Licensed and enabled | Render fully interactive. |

Feature keys: `frequency`, `escalation`, `profiles`, `tool_guard`, `audit`, `alerting`.

**Never hide premium sections.** Always render them — the visibility-while-locked is a deliberate product decision for discoverability.

### Inline Activation Flow

1. User clicks "Activate" CTA on any locked section.
2. Modal/inline input for JWT license key.
3. `POST /api/activate` with `{key: "..."}`.
4. Response includes `state` and updated `premium_features`.
5. If `state === "valid"`: re-render all sections using the new manifest. **No page reload.**
6. If `state === "expired"` or `"invalid"`: show error message, keep sections locked.

Deactivation: `POST /api/deactivate` → same re-render flow in reverse.

---

## 4. SSE Data Flow

Connect to `GET /api/events` using the browser's `EventSource` API. Three event types:

**`scan_result`** (OSS) — lightweight scan summary for the history panel. Emitted after every `Pipeline.inspect()` call, not just playground scans. Shape: `{scan_id, safe, finding_count, duration_ms, timestamp}`.

**`audit`** (Premium) — full `AuditEvent` object. Only emitted when `audit` feature is `"available"`. The payload depth depends on `audit_verbosity` config — handle gracefully.

**`alert`** (Premium) — full `Alert` object. Only emitted when `alerting` feature is `"available"`. The `context` field is rule-specific and should be rendered as expandable detail.

Server sends `:keepalive` comments every ~15s. The `EventSource` API handles reconnection automatically. No client-side ping needed.

### Buffering

The SSE stream is unbounded. The frontend should maintain an in-memory ring buffer per event type (suggested: 1000 entries for audit, 200 for alerts, 500 for scan history). Oldest entries drop when the buffer fills. The Dashboard panels should render from these buffers, not from accumulated DOM nodes.

---

## 5. Config Field Metadata

The `GET /api/config` response includes a `fields` array that drives form generation. Each entry has:

- `name` — exact Python field name (use as form field key and `PUT` payload key)
- `type` — JSON type hint: `"boolean"`, `"number"`, `"string"`, `"array"`, `"enum"`
- `default` — default value
- `description` — human-readable label
- `tier` — `"oss"` or `"premium"` (drives the disabled/CTA behavior)
- `section` — config editor section grouping
- `constraints` — validation rules (shape varies by type, see below)

### Constraint shapes

| Field type | Constraint shape |
|---|---|
| number | `{min?: number, max?: number, finite: true}` |
| enum | `{values: string[]}` |
| boolean | (none) |
| array | `{item_type: "string"}` |
| cross-field | `{requires: "hash_key", when: {redaction_mode: "hash", anonymize: true}}` |

The `tier` field on a config entry determines whether it's interactive or disabled+CTA. Cross-reference with the `premium_features` manifest: a field with `tier: "premium"` and `premium_features[section] === "locked"` is disabled with CTA. All other combinations are editable.

### Tier-threshold invariant

`tier1_threshold < tier2_threshold < tier3_threshold`, and `tier3_threshold >= 30.0` (hardcoded floor — Tier 3 cannot be disabled). The backend enforces this; the frontend should validate client-side and show the constraint before submit.

---

## 6. Error Conventions

**422 responses** from `PUT /api/config` include per-field errors:

```json
{
  "detail": [
    {"field": "tier3_threshold", "message": "tier3 must be >= 30.0, got 20.0"},
    {"field": "fail_mode", "message": "must be 'open', 'closed', or 'degraded'"}
  ]
}
```

Render errors inline next to the relevant form field.

**Pipeline errors** are non-fatal strings in `PipelineResult.errors`. They indicate degraded operation (e.g., "presidio not installed: anonymization skipped", "frequency hook: ..."). Display them as warnings in the playground result view, not as blocking errors.

**Scanner errors** appear in `ScanResult.error`. The prefix convention tells you the failure type:
- `ScannerTimeout:` — scanner exceeded its timeout budget
- `ScannerCircuitOpen:` — circuit breaker tripped after consecutive timeouts
- Other prefixes are Python exception class names (e.g., `ImportError:`)

---

## 7. Hermes Desktop Embedding

The Console runs standalone in any browser, but its primary embedding target is Hermes Desktop's webview. Integration points the frontend should support:

- **Theme:** Respect `prefers-color-scheme` media query. Additionally, accept a `?theme=dark|light` query parameter that Hermes passes to override the system preference.
- **Session forwarding:** Accept `?session_id=...` query parameter. When present, auto-populate the playground's session ID field and auto-filter the session inspector to that session.
- **Port:** The URL is `http://localhost:{port}/` where port defaults to 8384 but is configurable. The frontend doesn't need to know the port — it's relative.

---

## 8. Tech Constraints

- **No build step.** Vanilla HTML/JS/CSS. No JSX, no TypeScript compilation, no bundler.
- **No npm dependencies.** Everything ships as Python package data inside the wheel.
- **CDN is OK for charting.** Chart.js from cdnjs is acceptable for heatmaps and timelines. Keep it to one library.
- **No localStorage for critical state.** In-memory only. Scan history, event buffers, and filter state are ephemeral — they reset on page reload. This is by design (the backend ring buffers are the source of truth).
- **Zero impact on scan path.** The Console server must not add latency to `Pipeline.inspect()`. The server is observability-only — it reads callbacks, it doesn't insert into the pipeline.

---

## 9. Open Items

These are known gaps between the spec and the current codebase that the backend will need to address before or alongside frontend work:

1. **`normalized_text` not in PipelineResult.** The playground's normalized-diff view needs the normalized text. Either extend `PipelineResult` or add a `normalized_text` field to the `/api/scan` response wrapper.
2. **Config field metadata generation.** The backend needs to introspect `PetasosConfig` dataclass fields and produce the `fields` array with types, defaults, descriptions, tiers, sections, and constraints. This doesn't exist yet.
3. **Scan history ring buffer.** The backend needs an in-memory ring buffer of recent scan summaries for `GET /api/scan-history`. Not yet implemented.
4. **SSE `scan_result` event emission.** The backend needs a hook that emits a lightweight scan summary SSE event after every `Pipeline.inspect()` call, independent of audit/alert callbacks.
5. **`/api/profiles` endpoint.** The backend needs to expose the ProfileResolver's loaded profiles as JSON.

---

## Decisions Carried Forward

1. **Form generation from metadata, not hardcoded.** The Config Editor reads `GET /api/config` field metadata and generates the form dynamically. This means new config fields ship without frontend changes.

2. **Premium manifest is the single rendering gate.** The frontend never guesses what's locked — it reads `premium_features` from every relevant response and renders accordingly.

3. **SSE for real-time, polling for health.** Audit and alert events stream via SSE. Scanner health and scan history use polling (10s) as a fallback, with SSE `scan_result` events as an optimization.

4. **No page reload on activation.** `POST /api/activate` returns the updated manifest; the frontend re-renders in place.

5. **Session-restart notice is mandatory.** Every successful config PUT displays the restart notice. This is a Hermes Desktop platform constraint, not a UX preference.

## Done When

- [ ] Frontend renders Config Editor from `GET /api/config` field metadata
- [ ] All config sections render; premium sections disabled+CTA when locked
- [ ] Config PUT shows validation errors inline and session-restart notice on success
- [ ] Scan Playground submits, renders full PipelineResult breakdown
- [ ] SSE connection established, events rendered in audit log / alert feed
- [ ] Scan history and scanner health panels render from polling/SSE
- [ ] Inline activation flow works end-to-end without page reload
- [ ] `?theme=dark|light` and `?session_id=...` query params honored
- [ ] No build step — ships as static HTML/JS/CSS

## Out of Scope

- Native Hermes Desktop UI components (that's a Hermes concern)
- Multi-user auth (localhost-only tool)
- Persistent storage (ring buffers are ephemeral)
- OpenTelemetry export
- Config file I/O (consumer's job)
- Automated remediation actions
