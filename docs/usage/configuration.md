# Configuration guide

This page walks every setting in the Petasos Config Editor, in the same groups
and the same order the editor shows them. If you are reading the editor and the
docs side by side, they line up one-to-one. Profiles are the "start here" bundle:
pick one that matches your use case and you rarely need to touch anything else.

> Verified against source at commit `770401e`. The section list, the field count,
> and the set of documented fields are pinned to live source by
> `tests/test_docs_usage_consistency.py`, so this page cannot silently fall out of
> step with the editor.

The editor shows 11 sections, in this render order:

<!-- petasos-doc-assert: config_sections=profiles,anonymization,fail_mode,tool_guard,scanning,normalization,escalation,frequency,audit,alerting,session -->

1. Profiles
2. PII / Anonymization
3. Fail Mode
4. Tool Call Guard
5. Scanning
6. Normalization
7. Escalation Tiers
8. Frequency Tracking
9. Audit
10. Alerting
11. Session Management

Together these cover 62 editable fields.

<!-- petasos-doc-assert: config_field_count=62 -->

Each field below is named exactly as it appears in config files and the editor.
Where a field has a safe range or a fixed set of choices, it is given.

## 1. Profiles

*Pick a ready-made settings bundle for your use case (coding agent, customer
service, and so on) instead of tuning every knob by hand. Start here if you are
not sure what to change.*

- `profile_name`: selects a preset tuning bundle. The five built-ins are
  `general`, `customer_service`, `code_generation`, `research`, and `admin`, each
  adjusting rule sensitivity, severity handling, and tool permissions. Leave it
  unset to run with no profile.

## 2. PII / Anonymization

*Mask personal details (names, emails, card numbers) the scanners find so they do
not pass through in the clear. Leave on if your agent handles real user data.*

- `anonymize`: after scanning, replace any personal information found with
  placeholders so it does not travel further. Off by default; turn it on when
  conversations may contain other people's data.
- `pii_entities`: narrow which detected types are actually hidden at the
  anonymize step (for example, list only `EMAIL_ADDRESS` to redact emails and
  leave the rest untouched). Empty means anonymize every detected type. This
  filters only what is hidden, not what the scanner looks for.
- `redaction_mode`: how a found value is hidden. One of `redact` (a typed
  placeholder), `replace` (numbered placeholders), `hash` (a non-reversible
  scrambled code, useful for matching records without revealing them), or `mask`
  (hide all but the last few characters).
- `hash_key`: the secret key used when `redaction_mode` is `hash`. Required for
  hash mode, ignored otherwise, and never displayed in full.

## 3. Fail Mode

*Choose what happens to a message when a scanner crashes or times out: block it,
let it through, or block only on a hard failure. The safe default blocks on
failure.*

- `fail_mode`: one of `open` (let content pass when a scanner breaks), `degraded`
  (the default: block on partial or total scanner failure, while the always-on
  syntactic check still runs), or `closed` (strictest: also block immediately
  when the syntactic check finds something critical, without waiting for the
  other scanners).

## 4. Tool Call Guard

*Check the tools your agent tries to call and cap how fast it can spawn
sub-agents, before any of it runs. Tighten this for agents that touch the file
system or the shell.*

- `tool_guard_enabled`: check each tool call before it runs, scanning its inputs
  for smuggled instructions and blocking calls from escalated conversations. Off
  lets all tool calls through unchecked.
- `subagent_lineage_enabled`: make a spawned helper sub-agent start at least as
  restricted as the conversation that launched it, so a flagged session cannot
  reset its record by handing work to a fresh child. Needs the host to report
  sub-agent start and stop; if it does not, this quietly does nothing.
- `delegate_fanout_enabled`: cap how fast one conversation can spin up helper
  sub-agents, so a hostile session cannot flood the system with delegated tasks.
  The cap tightens automatically as the session's risk rises.
- `lineage_max_depth`: how many levels up the family tree to look when deciding a
  sub-agent's inherited restriction level (minimum 1). The default leaves
  headroom while keeping the lookup fast.
- `lineage_max_edges`: how many active sub-agent relationships to remember at once
  (minimum 1). When full, the oldest link is dropped, a ceiling so the
  bookkeeping cannot grow without bound.
- `lineage_edge_ttl_seconds`: how long to keep a sub-agent's link to its parent
  before treating it as stale (minimum 0.01). Set it comfortably longer than a
  realistic helper's lifetime.
- `delegate_max_fanout_per_window`: how many helper sub-agents a calm conversation
  may launch within the window below (minimum 1). The allowance halves once the
  session looks risky and drops to one when flagged.
- `delegate_fanout_window_seconds`: the time span the spawn allowance is measured
  over (minimum 0.01). A shorter window forgives bursts sooner; a longer one
  keeps a tighter lid on sustained spawning.
- `delegate_tool_names`: the tool names that count as launching a helper
  sub-agent (by default just `delegate_task`). Add your host's own delegation
  tool names if they differ.
- `egress_sink_tools`: the tools that send content out of the machine (email,
  social posts, external web requests, webhooks, clipboard). Detected personal
  data is blocked only when an agent tries to send it through one of these;
  writing to local files or the terminal is never blocked for personal data. Set
  these to your host's actual outbound tool names.
- `source_taint_namespaces`: tool namespaces (by name prefix, such as a banking or
  health connector) whose returned content must not leave again through an egress
  sink. Once a tool in one of these groups returns data, that exact text is blocked
  from any `egress_sink_tools` tool above, even when it is not flagged as personal
  data, which catches a plain account balance or amount the PII scanner would miss.
  Empty (the default) turns the fence off. Matching is exact-text only, so a
  paraphrased or re-encoded copy is not caught.
- `taint_min_span_length`: the shortest piece of restricted-source content the fence
  will remember (minimum 1; default 12 characters). Short, common values (a price
  like $5.00, a year like 2026) fall below this and are ignored, so they cannot
  block every later message that happens to contain them. Raise it if benign
  messages get blocked for sharing a common phrase; lower it to catch shorter
  sensitive values at the cost of more false alarms.

## 5. Scanning

*The core scan settings: which direction to scan (incoming, outgoing, or both)
and how widely to look for personal data. Also sets per-scanner time limits and
when to stop calling one that keeps failing.*

- `direction`: the default text flow. `inbound` is messages from the user to the
  agent; `outbound` is the agent's replies going out. Some scanners apply
  different checks per direction.
- `scanner_timeout_seconds`: how long to wait for a slow scanner before giving up
  on it for that scan (0.01 to 60 seconds). A timeout counts as a scanner
  failure, so the fail mode setting decides what happens next.
- `scanner_circuit_breaker_threshold`: how many consecutive timeouts before a
  scanner is temporarily benched (minimum 1). Any scan that does not time out
  resets the count.
- `scanner_circuit_breaker_cooldown_seconds`: how long a benched scanner sits out
  before another chance (minimum 0.01). While benched it is skipped instantly but
  still counts as failed, so the fail mode decides whether content is blocked
  meanwhile; the zero-dependency syntactic check keeps running regardless.
- `presidio_entities`: replace the PII scanner's detected entity list wholesale.
  Leave unset to use the curated default (the security-relevant types), which
  deliberately omits noisier types that misfire on file paths and code.
- `presidio_entities_extra`: add entity types back on top of the curated default
  without replacing it (for example, add `URL` to detect web addresses again).
  Entries are uppercased automatically.
- `presidio_score_threshold`: how confident the PII scanner must be before it
  reports a match (0 to 1). Higher means fewer false alarms but more misses;
  setting it to 0 reports every candidate and brings back the noise the curated
  default is meant to remove.

## 6. Normalization

*Undo tricks that hide malicious text from the scanners (look-alike letters,
invisible characters, leetspeak, encoded blobs) before anything is checked. Most
operators leave this on as-is.*

- `normalize_nfkc`: rewrite stylized or alternate-form characters (such as
  fullwidth letters) into plain text before scanning. Turning it off also
  disables follow-up cleanup passes that depend on it.
- `strip_zero_width`: remove invisible characters that can smuggle instructions
  past the filters. Normal text looks identical with this on, so there is no
  reason to turn it off in everyday use.
- `map_homoglyphs`: convert look-alike letters (such as a Cyrillic character
  posing as a Latin one) to their plain equivalents. Turning it off makes scans
  slightly faster but easier to evade.
- `detect_rtl_override`: flag characters that reverse the reading direction of
  text, a trick that disguises content by displaying it backwards. This only
  raises the flag; the actual removal is handled by `strip_zero_width`.
- `fold_leet`: add a decoded copy of leetspeak text (such as "1gn0r3" for
  "ignore") for the injection rules to check; the original is never altered. Note
  that the built-in syntactic scanner always decodes leetspeak regardless of this
  toggle, which affects only direct `normalize()` callers.
- `decode_encoded_payloads`: decode and rescan base64, hex, and ROT13 blobs so a
  wrapped injection is caught at full severity instead of slipping through as a
  low-priority flag. Unlike `fold_leet`, turning this off does disable the decode
  stage inside the syntactic scanner, reopening the encoded-payload gap. Decoding
  is bounded by size, count, and depth caps, so it adds no false positives on
  ordinary encoded data.

## 7. Escalation Tiers

*As a conversation keeps misbehaving, these risk-score cutoffs ratchet
enforcement up one tier at a time. Advanced: the built-in tiers are sensible
defaults.*

- `escalation_enabled`: whether scan results report the conversation's escalation
  tier. Turning it off does not relax enforcement: sessions still terminate at
  the top tier, the tool-call guard still blocks escalated conversations, and
  tier alerts still fire.
- `tier1_threshold`: risk score at which a conversation gets light extra scrutiny;
  tool calls still work but warnings are attached (minimum 0). Lower is stricter;
  must stay below `tier2_threshold`.
- `tier2_threshold`: risk score at which tool calls are blocked except those
  explicitly exempted (minimum 0). Lower is stricter; must sit between
  `tier1_threshold` and `tier3_threshold`.
- `tier3_threshold`: risk score at which the conversation is shut down and stays
  terminated. It can never take effect below the built-in floor of 30, which is
  why its minimum is 30 and why Tier 3 cannot be disabled.

## 8. Frequency Tracking

*Tracks how risky each conversation looks over time, so repeated suspicious
behavior adds up instead of being judged one message at a time. Advanced: the
defaults are sensible.*

- `frequency_enabled`: keep a running risk score per conversation. Turning it off
  also stops the automatic escalation that depends on the score.
- `frequency_half_life_seconds`: how quickly an idle conversation's risk score
  fades; after this much quiet time the score halves (minimum 0.01). Higher means
  suspicion is remembered longer.
- `frequency_weights`: fine-tune how much each kind of finding adds to the score
  (for example, injection attempts counting more than odd encodings). Leave unset
  for the built-in weights; an explicitly empty table instead stops findings from
  adding to the score at all.
- `rolling_window_seconds`: the recent time span over which flagged scans are
  counted per conversation (minimum 0.01). A bigger window catches slow, patient
  misbehavior.
- `rolling_threshold`: how many flagged scans within the window mark a
  conversation for extra scrutiny (minimum 1), even when each finding was minor.

## 9. Audit

*Decide whether each scan is recorded for later review, and how much detail to
keep. Turn the detail up when you need an investigation trail.*

- `audit_enabled`: record an audit event for every scan. Turning it off disables
  the activity feed and anything built on audit events.
- `audit_verbosity`: how much detail each record carries. One of `minimal` (the
  verdict and a finding count), `standard` (adds findings and session-risk
  detail), or `verbose` (adds full scanner output and a settings snapshot).
- `audit_emit_findings`: emit one log line per finding (rule, severity,
  confidence, direction) for offline false-positive tuning. Off by default;
  see the reference-plugin capture-window note.

## 10. Alerting

*Raise a warning when something looks off (rapid-fire scanning, a spike in
personal data, repeated blocks) without flooding you with duplicates. Advanced:
the defaults cover the common cases.*

- `alert_enabled`: watch scan results for suspicious patterns and fire warnings.
  Off silences all alerts.
- `alert_cooldown_seconds`: minimum quiet time before the same alert can fire
  again for the same conversation (minimum 0.01). Critical alerts ignore this.
- `alert_per_minute_cap`: the most alerts a single rule may fire per minute across
  all conversations (minimum 1). Critical alerts have their own separate cap.
- `alert_per_hour_cap`: the long-term per-hour ceiling behind the per-minute cap
  (minimum 1).
- `alert_critical_per_minute_cap`: a separate per-minute allowance just for
  critical alerts, which skip the normal limits so emergencies always get through
  (minimum 1).
- `alert_high_severity_threshold`: the minimum seriousness a finding needs to
  trigger the high-severity alert. One of `critical`, `high`, `medium`, `low`, or
  `info`; lower fires for almost everything.
- `alert_rapid_fire_count`: how many scans from one conversation inside the window
  count as a rapid-fire burst (minimum 1). Lower is more sensitive.
- `alert_rapid_fire_window_seconds`: the time span over which one conversation's
  scans are counted for rapid-fire detection (minimum 0.01).
- `alert_cross_session_burst_count`: how many different conversations must show
  findings within the window before the coordinated-burst alert fires
  (minimum 1).
- `alert_cross_session_burst_window_seconds`: the time span used to spot findings
  across multiple conversations at once (minimum 0.01).
- `alert_pii_volume_threshold`: the total pieces of personal data detected within
  the window, across all conversations, that count as a leak spike (minimum 1).
- `alert_pii_volume_window_seconds`: the time span over which detected personal
  data is totalled for the leak-spike alert (minimum 0.01).
- `alert_ring_buffer_capacity`: how many recent events the alert rules keep in
  memory for their counting (minimum 1). The burst thresholds above must fit
  within it.
- `alert_per_session_contribution_cap`: the most alerts any single conversation
  may contribute per rule per minute (minimum 1), so one noisy session cannot use
  up the shared allowance. Must not exceed `alert_per_minute_cap`.
- `alert_max_session_contribution_entries`: a memory-safety limit on how many
  conversation-and-rule combinations the alert fairness tracking follows at once
  (minimum 1). When full, alerts from brand-new combinations are dropped until
  stale entries expire.

## 11. Session Management

*Caps on how many conversations are tracked at once, how long each is remembered,
and how fast new ones may start. Advanced: raise these only for high-traffic
deployments.*

- `max_sessions`: the most conversations tracked at once (minimum 1). When full,
  the oldest finished-with sessions are dropped first; during a flood of new
  conversations, new ones may temporarily go untracked instead.
- `session_ttl_seconds`: how long an idle conversation stays tracked before
  cleanup (minimum 0.01; default one hour). Cleanup happens opportunistically
  during later activity, not on an exact timer.
- `max_new_sessions_per_minute`: caps how many brand-new conversations may start
  per minute (minimum 1), but only once the session store is already full.
  Protects against floods of throwaway sessions.
- `max_terminated_tombstones`: how many terminated conversations to remember by ID
  after cleanup (minimum 1), so a banned session cannot sneak back in under the
  same name.

## Advanced: not in the Config Editor

One field of the runtime configuration is deliberately not exposed in the editor,
so do not conclude this page is incomplete if you cannot find it:

- `session_secret`: the secret used to bind and verify session identity. It is
  excluded from the editor by design (it is the single field in the difference
  between the full runtime config and the editor's field set) and is set out of
  band, not through the UI.

---

<!-- Drift-guard index: the full set of editor-surfaced field names documented
     above. Kept in sync with petasos.console._config_meta._FIELD_META by
     tests/test_docs_usage_consistency.py. -->
<!-- petasos-doc-assert: config_fields=profile_name,anonymize,pii_entities,redaction_mode,hash_key,fail_mode,tool_guard_enabled,subagent_lineage_enabled,delegate_fanout_enabled,lineage_max_depth,lineage_max_edges,lineage_edge_ttl_seconds,delegate_max_fanout_per_window,delegate_fanout_window_seconds,delegate_tool_names,egress_sink_tools,direction,scanner_timeout_seconds,scanner_circuit_breaker_threshold,scanner_circuit_breaker_cooldown_seconds,presidio_entities,presidio_entities_extra,presidio_score_threshold,normalize_nfkc,strip_zero_width,map_homoglyphs,detect_rtl_override,fold_leet,decode_encoded_payloads,escalation_enabled,tier1_threshold,tier2_threshold,tier3_threshold,frequency_enabled,frequency_half_life_seconds,frequency_weights,rolling_window_seconds,rolling_threshold,audit_enabled,audit_verbosity,audit_emit_findings,alert_enabled,alert_cooldown_seconds,alert_per_minute_cap,alert_per_hour_cap,alert_critical_per_minute_cap,alert_high_severity_threshold,alert_rapid_fire_count,alert_rapid_fire_window_seconds,alert_cross_session_burst_count,alert_cross_session_burst_window_seconds,alert_pii_volume_threshold,alert_pii_volume_window_seconds,alert_ring_buffer_capacity,alert_per_session_contribution_cap,alert_max_session_contribution_entries,max_sessions,session_ttl_seconds,max_new_sessions_per_minute,max_terminated_tombstones,source_taint_namespaces,taint_min_span_length -->
