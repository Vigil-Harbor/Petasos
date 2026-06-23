"""Config field metadata introspection for the console Config Editor."""

from __future__ import annotations

import dataclasses
import logging
import typing
from typing import Any, get_args, get_origin, get_type_hints

from petasos.config import _SECRET_FIELDS, PetasosConfig

_logger = logging.getLogger(__name__)

# Resolve stringified annotations to real types once
_RESOLVED_HINTS: dict[str, Any] = {}


def _get_hints() -> dict[str, Any]:
    if not _RESOLVED_HINTS:
        import collections.abc

        import petasos._types as _types_mod
        import petasos.config as _config_mod

        ns = {**vars(_types_mod), **vars(_config_mod), "Mapping": collections.abc.Mapping}
        try:
            _RESOLVED_HINTS.update(get_type_hints(PetasosConfig, globalns=ns))
        except Exception:
            _logger.warning("Failed to resolve type hints — falling back to field annotations")
            for f in dataclasses.fields(PetasosConfig):
                _RESOLVED_HINTS[f.name] = f.type
    return _RESOLVED_HINTS


_FIELD_META: dict[str, dict[str, Any]] = {
    "normalize_nfkc": {
        "description": "Apply Unicode NFKC normalization to collapse compatibility variants.",
        "help_plain": (
            "Rewrites stylized or alternate-form characters (like fullwidth letters) into"
            " plain standard text. This feeds the ML scanners and PII anonymization, which"
            " see the normalized text; the built-in syntactic scanner re-normalizes its own"
            " input regardless of this setting, so the toggle does not gate built-in"
            " findings. Leave it on so the ML and PII stages aren't handed fancy-lettering"
            " evasions."
        ),
        "section": "normalization",
    },
    "strip_zero_width": {
        "description": "Remove zero-width characters that can hide injections.",
        "help_plain": (
            "Removes invisible characters that can be hidden inside text to smuggle"
            " instructions past the filters. This cleans the text handed to the ML scanners"
            " and PII anonymization; the built-in syntactic scanner re-strips its own input"
            " regardless of this setting, so the toggle does not gate built-in findings."
            " Normal text looks exactly the same with this on, so there's no reason to turn"
            " it off in everyday use."
        ),
        "section": "normalization",
    },
    "map_homoglyphs": {
        "description": "Map look-alike Unicode characters to their ASCII equivalents.",
        "help_plain": (
            'Converts look-alike letters (such as a Cyrillic "а" posing as a Latin "a") to'
            " their plain equivalents before the ML scanners and PII anonymization see the"
            " text; the built-in syntactic scanner re-maps its own input regardless of this"
            " setting, so the toggle does not gate built-in findings. Turning it off makes"
            " scans slightly faster but hands the ML and PII stages easier-to-evade text."
        ),
        "section": "normalization",
    },
    "decode_encoded_payloads": {
        "description": ("Decode base64/hex/ROT13 blobs and rescan the plaintext for injections."),
        "help_plain": (
            "Catches attacks hidden inside encoded blobs — a base64-, hex-, or"
            ' ROT13-wrapped "ignore all previous instructions" is decoded and rescanned,'
            " so it is caught at full severity instead of slipping through as a low-priority"
            " encoding flag. Unlike leetspeak decoding (which is always on), turning this"
            " off DOES disable the decode stage inside the built-in syntactic scanner,"
            " reopening the encoded-payload gap. Decoding is bounded (size, count, and depth"
            " caps) and only ever raises a flag on a real injection, so it adds no false"
            " positives on ordinary encoded data."
        ),
        "section": "normalization",
    },
    "direction": {
        "description": (
            "Default scan direction: inbound (user to agent) or outbound (agent to user)."
        ),
        "help_plain": (
            'Sets which way the text is flowing by default: "inbound" means messages coming'
            ' from the user to the agent, "outbound" means the'
            " agent's replies going out. Individual scanners may apply different checks"
            " depending on the direction."
        ),
        "section": "scanning",
    },
    "fail_mode": {
        "description": (
            "What happens if a scanner breaks: open = allow,"
            " closed = block, degraded = best-effort."
        ),
        "help_plain": (
            'Controls what happens when a scanner breaks mid-run: "open" lets content pass'
            ' anyway, while "degraded" (the default) and "closed" block it to stay safe.'
            ' "closed" is strictest — it also blocks immediately when the always-on pattern'
            " check finds something critical, without waiting for the other scanners."
        ),
        "section": "fail_mode",
        "constraints": {"values": ["open", "closed", "degraded"]},
    },
    "scanner_timeout_seconds": {
        "description": "How long to wait for a scanner before giving up.",
        "help_plain": (
            "How many seconds to wait for a slow scanner before giving up on it for that"
            " scan. Lower keeps scans snappy but cuts off slow scanners more often — and a"
            " timeout counts as a scanner failure, so the fail mode setting decides what"
            " happens next."
        ),
        "section": "scanning",
        "constraints": {"min": 0.01, "max": 60},
    },
    "scanner_circuit_breaker_threshold": {
        "description": "Consecutive timeouts before a scanner is temporarily benched.",
        "help_plain": (
            "How many times in a row a scanner must time out before it's temporarily"
            " benched so it stops slowing down every scan. Lower benches a misbehaving"
            " scanner sooner; any scan that doesn't time out resets the count."
        ),
        "section": "scanning",
        "constraints": {"min": 1},
    },
    "scanner_circuit_breaker_cooldown_seconds": {
        "description": "How long a benched scanner stays out before retrying.",
        "help_plain": (
            "How many seconds a benched scanner sits out before it gets another chance."
            " While benched it is skipped instantly but still counts as a failed scanner —"
            " so the fail mode setting decides whether content is blocked meanwhile; the"
            " built-in zero-dependency pattern check keeps running regardless."
        ),
        "section": "scanning",
        "constraints": {"min": 0.01},
    },
    "anonymize": {
        "description": "Replace detected personal info with typed placeholders like [EMAIL].",
        "help_plain": (
            "After scanning, replaces any personal information found (names, emails, and so"
            " on) with placeholders so it doesn't travel further. Off by default — turn it"
            " on when conversations may contain other people's data."
        ),
        "section": "anonymization",
    },
    "pii_entities": {
        "description": "Which detected PII entity types to anonymize (empty = all).",
        "help_plain": (
            "Narrows which kinds of detected personal information actually get hidden at the"
            " anonymize step — for example, list only EMAIL_ADDRESS to redact emails while"
            " leaving other detected PII untouched. Leave empty to anonymize every detected"
            " type (the default). This filters only what is hidden, not what the scanner"
            " looks for — detection scope is set by the Presidio entity settings."
        ),
        "section": "anonymization",
    },
    # PET-109: detection-scope fields. section "scanning" (not "anonymization") keeps
    # detection separate from the anonymize-stage filter (pii_entities), honoring D7.
    "presidio_entities": {
        "description": (
            "PII entity types the Presidio scanner detects (unset = curated default set)."
        ),
        "help_plain": (
            "Replaces the personal-info scanner's detected entity list wholesale. Leave unset"
            " to use the curated default — the security-relevant types like credit cards,"
            " SSNs, emails, and phone numbers — which deliberately omits noisier types (names,"
            " locations, dates, URLs) that misfire on file paths and code. Set your own list"
            " here only when you need a fully custom detection set."
        ),
        "section": "scanning",
    },
    "presidio_entities_extra": {
        "description": "Extra Presidio entity types to add on top of the default set.",
        "help_plain": (
            "Adds entity types back on top of the curated default without replacing it — for"
            ' example, add "URL" to detect web addresses again. Use this to opt one of the'
            " noisier types back in while keeping the rest of the safe default. Entries are"
            " uppercased automatically."
        ),
        "section": "scanning",
    },
    "presidio_score_threshold": {
        "description": "Minimum confidence (0-1) a Presidio match needs before it is reported.",
        "help_plain": (
            "How confident the personal-info scanner must be before it reports a match, from"
            " 0 to 1. Higher means fewer false alarms but more missed items; lower catches"
            " more but gets noisier. Setting it all the way to 0 reports every candidate and"
            " brings back a lot of the noise this scoping is meant to remove."
        ),
        "section": "scanning",
        "constraints": {"min": 0, "max": 1},
    },
    "redaction_mode": {
        "description": "How to hide PII: redact, replace, hash, or mask.",
        "help_plain": (
            'Chooses how found personal information is hidden: "redact" swaps it for a'
            ' typed placeholder, "replace" numbers each one, "hash" turns it into a'
            " scrambled code (useful for matching records without revealing them), and"
            ' "mask" hides all but the last few characters.'
        ),
        "section": "anonymization",
        "constraints": {"values": ["redact", "replace", "hash", "mask"]},
    },
    "hash_key": {
        "description": "Secret key for hash-mode redaction. Never shown in full.",
        "help_plain": (
            'The secret key used when redaction mode is "hash" — it makes the scrambled'
            " codes impossible to reverse without the key. Required for hash mode, ignored"
            " otherwise, and never displayed in full."
        ),
        "section": "anonymization",
    },
    "frequency_enabled": {
        "description": "Track per-session frequency scores for risk assessment.",
        "help_plain": (
            "Keeps a running risk score per conversation, so repeated suspicious behavior"
            " adds up instead of being judged one message at a time. Turning this off also"
            " stops the automatic escalation that depends on the score."
        ),
        "section": "frequency",
    },
    "escalation_enabled": {
        "description": "Watch each conversation and tighten checks automatically as risk builds.",
        "help_plain": (
            "Controls whether scan results report the conversation's escalation tier."
            " Turning it off does not relax enforcement — sessions still terminate at the"
            " top tier, the tool-call guard still blocks escalated conversations, and tier"
            " alerts still fire; a built-in emergency check can even still report the top"
            " tier on critical findings."
        ),
        "section": "escalation",
    },
    "profile_name": {
        "description": "Active scanning profile (e.g., general, code_generation, admin).",
        "help_plain": (
            'Picks a preset tuning bundle for a use case — built-ins are "general",'
            ' "customer_service", "code_generation", "research", and "admin" — each'
            " adjusting rule sensitivity, severity handling, and tool permissions. Leave"
            " unset to run without a profile."
        ),
        "section": "profiles",
    },
    "tool_guard_enabled": {
        "description": "Intercept tool calls and scan parameters for injection payloads.",
        "help_plain": (
            "Checks the agent's tool calls before they run, scanning their inputs for"
            " smuggled instructions and blocking calls from conversations that have"
            " escalated. Turning this off lets all tool calls through unchecked."
        ),
        "section": "tool_guard",
    },
    "audit_enabled": {
        "description": "Emit audit events for every pipeline inspection.",
        "help_plain": (
            "Records an audit event for every scan, so you can review afterwards what was"
            " checked and why decisions were made. Turning this off disables the activity"
            " feed and anything else built on audit events."
        ),
        "section": "audit",
    },
    "alert_enabled": {
        "description": "Evaluate alert rules and fire warnings on suspicious patterns.",
        "help_plain": (
            "Watches scan results for suspicious patterns — like rapid-fire scanning or a"
            " spike in detected personal information — and fires warnings when one appears."
            " Turning this off silences all alerts."
        ),
        "section": "alerting",
    },
    "alert_cooldown_seconds": {
        "description": "Minimum seconds between alerts of the same type.",
        "help_plain": (
            "Minimum quiet time, in seconds, before the same alert can fire again for the"
            " same conversation — stops one session repeating the same warning over and"
            " over. Critical alerts ignore this cooldown."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_per_minute_cap": {
        "description": "Maximum alerts per minute across all rules.",
        "help_plain": (
            "The most alerts a single rule may fire per minute, counting all conversations"
            " together. Higher = noisier but less chance of missing something; critical"
            " alerts have their own separate cap."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_per_hour_cap": {
        "description": "Maximum alerts per hour across all rules.",
        "help_plain": (
            "The most alerts a single rule may fire per hour — the long-term ceiling behind"
            " the per-minute cap. Lower keeps the alert feed quieter over sustained"
            " activity."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_critical_per_minute_cap": {
        "description": "Maximum critical-severity alerts per minute.",
        "help_plain": (
            "A separate per-minute allowance just for critical alerts, which skip the"
            " normal limits so that emergencies always get through. This cap is the only"
            " bound on them."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_high_severity_threshold": {
        "description": "Minimum severity that triggers the high-severity alert rule.",
        "help_plain": (
            'The minimum seriousness a finding needs to trigger the "high severity" alert.'
            ' Setting it lower (toward "info") fires alerts for almost everything; setting'
            ' it to "critical" alerts only on the worst findings.'
        ),
        "section": "alerting",
        "constraints": {"values": ["critical", "high", "medium", "low", "info"]},
    },
    "alert_rapid_fire_count": {
        "description": "Scan count that triggers the rapid-fire alert within the window.",
        "help_plain": (
            "How many scans from one conversation, inside the time window, count as a"
            " rapid-fire burst worth alerting on. Lower = more sensitive."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_rapid_fire_window_seconds": {
        "description": "Time window for rapid-fire detection.",
        "help_plain": (
            "The time span, in seconds, over which one conversation's scans are counted for"
            " rapid-fire detection. A longer window also catches slower bursts."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_cross_session_burst_count": {
        "description": "Session count that triggers the cross-session burst alert.",
        "help_plain": (
            "How many different conversations must show findings within the window before"
            " the coordinated-burst alert fires — a sign of an attack spread across"
            " sessions. Lower = more sensitive."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_cross_session_burst_window_seconds": {
        "description": "Time window for cross-session burst detection.",
        "help_plain": (
            "The time span, in seconds, used to spot findings appearing across multiple"
            " conversations at once. Longer = catches slower coordinated activity."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_pii_volume_threshold": {
        "description": "PII finding count that triggers the volume spike alert.",
        "help_plain": (
            "The total pieces of personal information detected within the window — across"
            " all conversations — that count as a leak spike worth alerting on. Lower ="
            " more sensitive."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_pii_volume_window_seconds": {
        "description": "Time window for PII volume spike detection.",
        "help_plain": (
            "The time span, in seconds, over which detected personal information is"
            " totalled for the leak-spike alert. The default five minutes is long enough to"
            " catch slow leaks."
        ),
        "section": "alerting",
        "constraints": {"min": 0.01},
    },
    "alert_ring_buffer_capacity": {
        "description": "Maximum number of recent alerts kept in memory.",
        "help_plain": (
            "How many recent events the alert rules keep in memory for their counting."
            " Bigger remembers more history at the cost of memory — and the burst"
            " thresholds above must fit within it."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_per_session_contribution_cap": {
        "description": "Max alerts one session can contribute per minute.",
        "help_plain": (
            "The most alerts any single conversation may contribute per rule per minute, so"
            " one noisy session can't use up the shared alert allowance and drown out"
            " everyone else. Must not exceed the per-minute cap."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "alert_max_session_contribution_entries": {
        "description": "Max per-session contribution tracker entries.",
        "help_plain": (
            "A memory-safety limit on how many conversation-and-rule combinations the alert"
            " fairness tracking can follow at once. Once full, alerts from brand-new"
            " combinations are dropped until stale entries expire."
        ),
        "section": "alerting",
        "constraints": {"min": 1},
    },
    "audit_verbosity": {
        "description": "How much detail audit events carry: minimal, standard, or verbose.",
        "help_plain": (
            'How much detail each audit record carries: "minimal" is just the verdict and a'
            ' finding count, "standard" adds the findings and session risk details,'
            ' "verbose" adds full scanner output and a settings snapshot. More detail ='
            " better for debugging, more data stored."
        ),
        "section": "audit",
        "constraints": {"values": ["minimal", "standard", "verbose"]},
    },
    "audit_emit_findings": {
        "description": "Emit one log line per finding for offline tuning (default off).",
        "help_plain": (
            "Debug capture window: when on, writes one log line per detection finding"
            " (rule, severity, confidence, direction) for every scan, so false-positive"
            " tuning can read straight from the logs. Leave off in normal operation; it"
            " multiplies log volume by the number of findings per scan, so turn it on"
            " only for a short capture session."
        ),
        "section": "audit",
    },
    "frequency_half_life_seconds": {
        "description": "How fast the frequency score decays when a session goes quiet.",
        "help_plain": (
            "How quickly a conversation's risk score fades when things go quiet, in"
            " seconds: after this much idle time the score drops by half. Higher ="
            " suspicion is remembered longer."
        ),
        "section": "frequency",
        "constraints": {"min": 0.01},
    },
    "frequency_weights": {
        "description": "Custom severity weights for frequency scoring (maps severity to weight).",
        "help_plain": (
            "Fine-tunes how much different kinds of findings add to the risk score — for"
            " example, injection attempts can count more than odd encodings. Leave unset to"
            " use the built-in weights (an explicitly empty table is different: it stops"
            " findings from adding to the score at all)."
        ),
        "section": "frequency",
    },
    "rolling_window_seconds": {
        "description": "Time window for the rolling scan counter.",
        "help_plain": (
            "The recent time span, in seconds, over which flagged scans are counted per"
            " conversation. A bigger window catches slow, patient misbehavior; a smaller"
            " one reacts only to quick bursts."
        ),
        "section": "frequency",
        "constraints": {"min": 0.01},
    },
    "rolling_threshold": {
        "description": "Scan count in the rolling window that triggers an alert.",
        "help_plain": (
            "How many flagged scans within the window mark a conversation for extra"
            " scrutiny (escalation tier 1), even when each individual finding was minor."
            " Lower = more sensitive to slow-drip behavior."
        ),
        "section": "frequency",
        "constraints": {"min": 1},
    },
    "tier1_threshold": {
        "description": "Risk score that moves a conversation to tier 1 (light extra scrutiny).",
        "help_plain": (
            "Risk score at which a conversation gets light extra scrutiny — tool calls"
            " still work, but warnings are attached. Lower = stricter (reached sooner);"
            " must stay below the tier 2 threshold."
        ),
        "section": "escalation",
        "constraints": {"min": 0},
    },
    "tier2_threshold": {
        "description": "Risk score for tier 2 (closer watch). Must be higher than tier 1.",
        "help_plain": (
            "Risk score at which enforcement gets serious: tool calls are blocked except"
            " those explicitly exempted. Lower = stricter; must sit between the tier 1 and"
            " tier 3 thresholds."
        ),
        "section": "escalation",
        "constraints": {"min": 0},
    },
    "tier3_threshold": {
        "description": "Tier 3 is the strictest level. Always on — can't be set below 30.",
        "help_plain": (
            "Risk score at which the conversation is shut down — the session is terminated"
            " and stays terminated. Lower = stricter, but it can never take effect below"
            " the built-in floor of 30."
        ),
        "section": "escalation",
        "constraints": {"min": 30},
    },
    "max_sessions": {
        "description": "Maximum concurrent sessions tracked.",
        "help_plain": (
            "The most conversations tracked at once; when the limit is hit, the oldest"
            " finished-with sessions are dropped first to make room. During a flood of"
            " brand-new conversations while full, new ones may temporarily go untracked"
            " instead (see the per-minute limit below). Higher = more memory used."
        ),
        "section": "session",
        "constraints": {"min": 1},
    },
    "session_ttl_seconds": {
        "description": "How long an idle session lives before being cleaned up.",
        "help_plain": (
            "How long, in seconds, an idle conversation stays tracked before being cleaned"
            " up (default one hour). Cleanup happens opportunistically during later"
            " activity, not on an exact timer."
        ),
        "section": "session",
        "constraints": {"min": 0.01},
    },
    "max_new_sessions_per_minute": {
        "description": "Rate limit on new session creation.",
        "help_plain": (
            "Caps how many brand-new conversations may start per minute — but it only"
            " kicks in once the session store is already full. Protects against floods of"
            " throwaway sessions designed to overwhelm tracking."
        ),
        "section": "session",
        "constraints": {"min": 1},
    },
    "max_terminated_tombstones": {
        "description": "Maximum terminated session tombstones kept.",
        "help_plain": (
            "How many terminated conversations to remember by ID after they're cleaned"
            " away, so a banned session can't sneak back in under the same name. Higher ="
            " longer memory for slightly more storage."
        ),
        "section": "session",
        "constraints": {"min": 1},
    },
    "subagent_lineage_enabled": {
        "description": "Inherit a parent's escalation tier into its delegated sub-agents.",
        "help_plain": (
            "When a conversation spawns a helper sub-agent, this makes the helper start at"
            " least as restricted as the conversation that launched it — so a flagged session"
            " can't wash its record clean by handing work to a fresh child. Needs the host to"
            " report sub-agent start/stop; if it doesn't, this quietly does nothing."
        ),
        "section": "tool_guard",
    },
    "delegate_fanout_enabled": {
        "description": "Rate-limit how many sub-agents a session may spawn.",
        "help_plain": (
            "Caps how fast one conversation can spin up helper sub-agents, so a noisy or"
            " hostile session can't flood the system by spraying delegated tasks. The cap"
            " tightens automatically as the session's risk level rises."
        ),
        "section": "tool_guard",
    },
    "lineage_max_depth": {
        "description": "Maximum ancestor chain walked when inheriting a sub-agent's tier.",
        "help_plain": (
            "How many levels up the family tree to look when deciding an inherited"
            " restriction level for a sub-agent. Sub-agents are normally shallow, so the"
            " default leaves plenty of headroom while keeping the lookup fast."
        ),
        "section": "tool_guard",
        "constraints": {"min": 1},
    },
    "lineage_max_edges": {
        "description": "Maximum parent↔child links tracked at once.",
        "help_plain": (
            "How many active sub-agent relationships to remember at a time. Once full, the"
            " oldest link is dropped to make room — a safety ceiling so the bookkeeping can't"
            " grow without bound under a flood of helpers."
        ),
        "section": "tool_guard",
        "constraints": {"min": 1},
    },
    "lineage_edge_ttl_seconds": {
        "description": "How long a parent↔child link stays valid (seconds).",
        "help_plain": (
            "How long to keep a sub-agent's link to its parent before treating it as stale."
            " Set this comfortably longer than a realistic helper's lifetime so the parent"
            " stays remembered for as long as the child might still be running."
        ),
        "section": "tool_guard",
        "constraints": {"min": 0.01},
    },
    "delegate_max_fanout_per_window": {
        "description": "Base number of sub-agent spawns allowed per time window.",
        "help_plain": (
            "How many helper sub-agents a calm conversation may launch within the time"
            " window below. The allowance is cut in half once the session looks risky, and"
            " down to one when it's flagged — a terminated session can't spawn at all."
        ),
        "section": "tool_guard",
        "constraints": {"min": 1},
    },
    "delegate_fanout_window_seconds": {
        "description": "Rolling window for the sub-agent spawn budget (seconds).",
        "help_plain": (
            "The span of time the spawn allowance above is measured over. A shorter window"
            " forgives bursts sooner; a longer one keeps a tighter lid on sustained"
            " sub-agent spawning."
        ),
        "section": "tool_guard",
        "constraints": {"min": 0.01},
    },
    "delegate_tool_names": {
        "description": "Tool names treated as sub-agent spawns for the fan-out budget.",
        "help_plain": (
            "The list of tool names that count as launching a helper sub-agent (by default,"
            ' just "delegate_task"). Anything named here is subject to the spawn rate limit;'
            " add your host's own delegation tool names if they differ."
        ),
        "section": "tool_guard",
    },
    "egress_sink_tools": {
        "description": "Tool names treated as egress sinks; the PII block applies only to these.",
        "help_plain": (
            "The tools that send content OUT of the machine — email, social posts, external"
            " web requests, webhooks, clipboard. Detected personal data (cards, SSNs, emails)"
            " is blocked only when an agent tries to send it through one of these. Writing to"
            " local files or the terminal is never blocked for personal data. Set these to your"
            " host's actual outbound tool names."
        ),
        "section": "tool_guard",
    },
    "source_taint_namespaces": {
        "description": (
            "Tool namespaces whose returned content may not be sent back out through an"
            " egress sink."
        ),
        "help_plain": (
            "Marks tool groups (by name prefix, such as a banking or health connector) whose"
            " results are sensitive. Once a tool in one of these groups returns data, that exact"
            " text is blocked from leaving through any egress sink above (email, web request,"
            " messaging), even when it is not recognized as personal data. This catches a plain"
            " account balance or amount the personal-data scanner would miss. Leave empty (the"
            " default) to turn the fence off; matching is exact-text only, so paraphrased or"
            " re-encoded copies are not caught."
        ),
        "section": "tool_guard",
    },
    "taint_min_span_length": {
        "description": "Shortest piece of restricted-source content the egress fence will track.",
        "help_plain": (
            "The minimum length, in characters, a piece of restricted-source content must reach"
            " before the egress fence remembers it. Short, common values (a price like $5.00, a"
            " year like 2026) fall below this and are ignored, so they cannot block every later"
            " message that happens to contain them. Raise it if benign messages get blocked for"
            " sharing a common phrase; lower it to catch shorter sensitive values at the cost of"
            " more false alarms. Only applies to the restricted-source fence above."
        ),
        "section": "tool_guard",
        "constraints": {"min": 1},
    },
}

# Fields deliberately kept off the Config Editor surface. Three distinct
# rationales: `session_secret` is a secret kept off the wire (never serialized to
# the UI); `fold_leet` is a retired no-op control (PET-143): leet folding is
# always-on by design (PET-97 Decision 6), so surfacing the flag would advertise a
# knob that cannot move a detection outcome; `detect_rtl_override` is a retired
# inert control (PET-151): the pipeline keeps only `normalize()`'s `.normalized`
# text (RTL detection sets only a discarded side-channel flag) and the built-in
# scanner re-derives RTL detection at its hardcoded default, so the toggle moves no
# detection, ML, or PII outcome anywhere in the shipped pipeline. All three fields
# are retained on PetasosConfig for `normalize()`-parity but are not bindable here.
_EXCLUDED_FIELDS = frozenset({"session_secret", "fold_leet", "detect_rtl_override"})


@dataclasses.dataclass(frozen=True, slots=True)
class ConfigSection:
    """Display metadata for one Config Editor section group."""

    key: str  # matches the per-field `section` value
    label: str  # human-readable group title
    description: str  # one-line group summary
    default_collapsed: bool


# Ordered tuple — tuple position IS the canonical render order.
# Every section defaults collapsed: the Config Editor opens fully collapsed so
# each group's detail is requested on click (supersedes PET-114 D3's open-first
# five). Tuple position is still the canonical render order.
# The 11 keys are exactly the in-use `section` values on the _FIELD_META fields.
# The "unknown" missing-metadata sentinel is deliberately NOT a registry entry:
# a field that ever synthesizes section="unknown" is rendered by the frontend's
# trailing-group fallback (and the exact-coverage test points the fix at the
# _FIELD_META gap, not here).
_SECTION_REGISTRY: typing.Final[tuple[ConfigSection, ...]] = (
    ConfigSection(
        "profiles",
        "Profiles",
        "Pick a ready-made settings bundle for your use case (coding agent,"
        " customer service, and so on) instead of tuning every knob by hand."
        " Start here if you are not sure what to change.",
        default_collapsed=True,
    ),
    ConfigSection(
        "anonymization",
        "PII / Anonymization",
        "Mask personal details (names, emails, card numbers) the scanners find"
        " so they do not pass through in the clear. Leave on if your agent"
        " handles real user data.",
        default_collapsed=True,
    ),
    ConfigSection(
        "fail_mode",
        "Fail Mode",
        "Choose what happens to a message when a scanner crashes or times out:"
        " block it, let it through, or block only on a hard failure. The safe"
        " default blocks on failure.",
        default_collapsed=True,
    ),
    ConfigSection(
        "tool_guard",
        "Tool Call Guard",
        "Check the tools your agent tries to call and cap how fast it can spawn"
        " sub-agents, before any of it runs. Tighten this for agents that touch"
        " the file system or the shell.",
        default_collapsed=True,
    ),
    ConfigSection(
        "scanning",
        "Scanning",
        "The core scan settings: which direction to scan (incoming, outgoing, or"
        " both) and how widely to look for personal data. Also sets per-scanner"
        " time limits and when to stop calling one that keeps failing.",
        default_collapsed=True,
    ),
    ConfigSection(
        "normalization",
        "Normalization",
        "Undo tricks that hide malicious text from the scanners (look-alike"
        " letters, invisible characters, leetspeak, encoded blobs) before"
        " anything is checked. Most operators leave this on as-is.",
        default_collapsed=True,
    ),
    ConfigSection(
        "escalation",
        "Escalation Tiers",
        "As a conversation keeps misbehaving, these risk-score cutoffs ratchet"
        " enforcement up one tier at a time. Advanced: the built-in tiers are"
        " sensible defaults.",
        default_collapsed=True,
    ),
    ConfigSection(
        "frequency",
        "Frequency Tracking",
        "Tracks how risky each conversation looks over time, so repeated"
        " suspicious behavior adds up instead of being judged one message at a"
        " time. Advanced: the defaults are sensible.",
        default_collapsed=True,
    ),
    ConfigSection(
        "audit",
        "Audit",
        "Decide whether each scan is recorded for later review, and how much"
        " detail to keep. Turn the detail up when you need an investigation"
        " trail.",
        default_collapsed=True,
    ),
    ConfigSection(
        "alerting",
        "Alerting",
        "Raise a warning when something looks off (rapid-fire scanning, a spike"
        " in personal data, repeated blocks) without flooding you with"
        " duplicates. Advanced: the defaults cover the common cases.",
        default_collapsed=True,
    ),
    ConfigSection(
        "session",
        "Session Management",
        "Caps on how many conversations are tracked at once, how long each is"
        " remembered, and how fast new ones may start. Advanced: raise these"
        " only for high-traffic deployments.",
        default_collapsed=True,
    ),
)


def generate_section_metadata() -> list[dict[str, Any]]:
    """Ordered section display metadata for the Config Editor UI.

    Returns a fresh list of fresh dicts each call (defensive copy — the
    registry source stays immutable). ``order`` is the 0-based render index.
    """
    return [
        {
            "key": s.key,
            "label": s.label,
            "description": s.description,
            "default_collapsed": s.default_collapsed,
            "order": i,
        }
        for i, s in enumerate(_SECTION_REGISTRY)
    ]


def _derive_type(annotation: Any) -> tuple[str, bool]:
    """Return (type_name, nullable) from a dataclass field annotation."""
    import types as _bt

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Handle T | None — both typing.Union and types.UnionType (Python 3.10+)
    is_union = origin is typing.Union or isinstance(annotation, _bt.UnionType)
    if is_union:
        if not args:
            args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            inner_type, _ = _derive_type(non_none[0])
            return inner_type, True
        return "string", True

    if annotation is bool:
        return "boolean", False
    if annotation is float or annotation is int:
        return "number", False
    if annotation is str:
        return "string", False
    if annotation is bytes:
        return "bytes", False

    if origin is tuple:
        return "array", False

    # Literal types
    ann_str = str(annotation)
    if "Literal" in ann_str:
        return "enum", False

    # Mapping types
    origin_name = getattr(origin, "__name__", str(origin)) if origin else ""
    if "Mapping" in origin_name or "MappingProxyType" in origin_name:
        return "object", False
    if "Mapping" in ann_str:
        return "object", False

    return "string", False


def generate_config_metadata() -> list[dict[str, Any]]:
    """Produce field metadata for every PetasosConfig field (except excluded)."""
    hints = _get_hints()
    result: list[dict[str, Any]] = []
    for f in dataclasses.fields(PetasosConfig):
        if f.name in _EXCLUDED_FIELDS:
            continue

        meta = _FIELD_META.get(f.name)
        if meta is None:
            _logger.warning("Config field %r missing from metadata mapping — synthesizing", f.name)
            meta = {"description": "No description available.", "section": "unknown"}

        annotation = hints.get(f.name, f.type)
        type_name, nullable = _derive_type(annotation)
        entry: dict[str, Any] = {
            "name": f.name,
            "type": type_name,
            "nullable": nullable,
            "default": _serialize_default(f.default),
            "description": meta["description"],
            "help_plain": meta.get("help_plain") or meta["description"],
            "section": meta["section"],
            # PET-146 D2: posture scope. Every field is per-Hermes-profile today
            # (no machine-global tier exists) — including fail_mode /
            # egress_sink_tools / source_taint_namespaces. Emitting "profile" on
            # every field locks the disclosure contract so a future global tier
            # can't silently relabel an existing field; the UI prints no "global"
            # marker while this stays uniformly "profile".
            "scope": "profile",
        }

        if f.name in _SECRET_FIELDS:
            entry["redacted"] = True

        if "constraints" in meta:
            entry["constraints"] = meta["constraints"]
        elif type_name == "enum":
            args = get_args(annotation)
            if not args:
                origin = get_origin(annotation)
                if origin is typing.Union:
                    for a in get_args(annotation):
                        if a is not type(None):
                            args = get_args(a)
                            break
            if args:
                entry["constraints"] = {"values": list(args)}

        result.append(entry)
    return result


def _serialize_default(val: Any) -> Any:
    if isinstance(val, tuple):
        return list(val)
    if val is dataclasses.MISSING:
        return None
    return val
