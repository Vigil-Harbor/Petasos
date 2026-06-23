from __future__ import annotations

import math
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from petasos._types import Direction

TIER3_FLOOR: Final[float] = 30.0

_BOOL_FIELDS: frozenset[str] = frozenset(
    {
        "normalize_nfkc",
        "strip_zero_width",
        "map_homoglyphs",
        "detect_rtl_override",
        "fold_leet",
        "decode_encoded_payloads",
        "anonymize",
        "frequency_enabled",
        "escalation_enabled",
        "tool_guard_enabled",
        "audit_enabled",
        "audit_emit_findings",
        "alert_enabled",
        "subagent_lineage_enabled",
        "delegate_fanout_enabled",
    }
)


def _validate_tier_thresholds(tier1: float, tier2: float, tier3: float) -> None:
    if not all(math.isfinite(v) for v in (tier1, tier2, tier3)):
        raise ValueError(f"thresholds must be finite, got {tier1}, {tier2}, {tier3}")
    if not (tier1 < tier2 < tier3):
        raise ValueError(f"thresholds must be strictly ascending: {tier1} < {tier2} < {tier3}")
    if tier3 < TIER3_FLOOR:
        raise ValueError(f"tier3 must be >= {TIER3_FLOOR}, got {tier3}")


_SECRET_FIELDS: frozenset[str] = frozenset({"hash_key"})


@dataclass(frozen=True, slots=True)
class PetasosConfig:
    # Normalization toggles
    normalize_nfkc: bool = True
    strip_zero_width: bool = True
    map_homoglyphs: bool = True
    detect_rtl_override: bool = True
    # By design not a detection control: leet folding is an always-on syntactic
    # posture (PET-97 Decision 6) and the built-in scanner re-folds internally with
    # hardcoded defaults regardless of this flag. Retained for normalize()-parity
    # (direct callers and tests); not surfaced as a console control (PET-143).
    fold_leet: bool = True
    # Decode-and-rescan reversible encodings (base64/hex/ROT13) inside the
    # built-in syntactic scanner (PET-98). Leet folding above is an intentional
    # always-on syntactic posture (not threaded into the scanner by design, no
    # longer a console control); decode_encoded_payloads, by contrast, IS threaded
    # into MinimalScanner's constructor, so turning it off genuinely disables the
    # decode stage in every pipeline build path.
    decode_encoded_payloads: bool = True

    # Scanning
    direction: Direction = "inbound"
    # open: ML failures ignored (pass-through)
    # degraded: partial or total ML failure → safe=False
    # closed: same as degraded + early-exit on CRITICAL from syntactic pre-filter
    fail_mode: Literal["open", "closed", "degraded"] = "degraded"

    # Per-scanner timeout + circuit breaker (PIPE-03). The 10s default is a
    # generous deadlock backstop for cold-start model loads while bounding the
    # latency-DoS window; the full-pipeline budget is < 250ms (CPU). The breaker
    # is advisory — after N consecutive timeouts a scanner is short-circuited to
    # an error ScanResult for a cooldown window; it never throws and never
    # bypasses the zero-dep syntactic pre-filter.
    scanner_timeout_seconds: float = 10.0
    scanner_circuit_breaker_threshold: int = 3
    scanner_circuit_breaker_cooldown_seconds: float = 30.0

    # Anonymization
    anonymize: bool = False
    pii_entities: tuple[str, ...] = ()
    # Presidio detection scoping (PET-109). presidio_entities=None -> the scanner's
    # curated default (DEFAULT_PRESIDIO_ENTITIES); a non-None tuple replaces it
    # wholesale. presidio_entities_extra is additive (opt back in e.g. "URL").
    presidio_entities: tuple[str, ...] | None = None
    presidio_entities_extra: tuple[str, ...] = ()
    presidio_score_threshold: float = 0.35
    redaction_mode: Literal["redact", "replace", "hash", "mask"] = "redact"
    hash_key: str | None = None

    # Session feature toggles
    frequency_enabled: bool = True
    escalation_enabled: bool = True
    profile_name: str | None = None
    tool_guard_enabled: bool = True
    audit_enabled: bool = True
    alert_enabled: bool = True

    # Alerting thresholds
    alert_cooldown_seconds: float = 60.0
    alert_per_minute_cap: int = 5
    alert_per_hour_cap: int = 20
    alert_critical_per_minute_cap: int = 20
    alert_high_severity_threshold: Literal["critical", "high", "medium", "low", "info"] = "high"
    alert_rapid_fire_count: int = 10
    alert_rapid_fire_window_seconds: float = 60.0
    alert_cross_session_burst_count: int = 3
    alert_cross_session_burst_window_seconds: float = 60.0
    alert_pii_volume_threshold: int = 20
    alert_pii_volume_window_seconds: float = 300.0
    alert_ring_buffer_capacity: int = 1000
    alert_per_session_contribution_cap: int = 2
    alert_max_session_contribution_entries: int = 10_000

    # Audit
    audit_verbosity: Literal["minimal", "standard", "verbose"] = "standard"
    # PET-136: verbosity-independent, default-off per-finding audit sink. When on,
    # the audit payload carries the per-finding list (rule_id/severity/confidence/
    # direction) regardless of audit_verbosity, so a minimal-verbosity capture
    # window still emits findings for offline false-positive tuning.
    audit_emit_findings: bool = False

    # Frequency tracking
    frequency_half_life_seconds: float = 60.0
    frequency_weights: Mapping[str, float] | None = None
    rolling_window_seconds: float = 300.0
    rolling_threshold: int = 10

    # Escalation thresholds
    tier1_threshold: float = 15.0
    tier2_threshold: float = 30.0
    tier3_threshold: float = 50.0

    # Session management
    max_sessions: int = 10_000
    session_ttl_seconds: float = 3600.0
    max_new_sessions_per_minute: int = 60
    max_terminated_tombstones: int = 10_000

    # Session token binding (FREQ-03 defense)
    session_secret: bytes | None = None

    # Sub-agent (delegate_task) session intelligence (PET-107).
    # A — lineage-linked escalation: a child's tier is max(own, parent-chain).
    # C — delegation fan-out gate: an escalation-tied budget on delegate spawns.
    # Both default on (PET-78 posture); A additionally needs the host's
    # subagent_start/subagent_stop hooks (degrades to C-only if unavailable).
    subagent_lineage_enabled: bool = True
    delegate_fanout_enabled: bool = True
    # Lineage chain walk + edge store bounds. depth 8 gives headroom over the
    # Hermes default delegation depth (<=1); edges/ttl parallel max_sessions /
    # session_ttl_seconds.
    lineage_max_depth: int = 8
    lineage_max_edges: int = 10_000
    lineage_edge_ttl_seconds: float = 3600.0
    # Fan-out budget: base spawns per rolling window at tier none. Default 3
    # mirrors Hermes's 3-concurrent delegate default; tier1 halves it, tier2
    # caps at 1, tier3 is already fully blocked by the tier ladder.
    delegate_max_fanout_per_window: int = 3
    delegate_fanout_window_seconds: float = 60.0
    # Tool names treated as delegation spawns. Stored RAW here; the guard
    # normalizes them through its own _normalize_tool_name at construction.
    delegate_tool_names: tuple[str, ...] = ("delegate_task",)
    # Tool names treated as egress sinks (outbound content: email/social/HTTP/webhook/
    # clipboard-out). The PII-finding block applies ONLY to these tools; internal tools
    # (write_file/terminal/execute_code/edit) are exempt. Stored RAW; canonicalized by the
    # plugin before matching (PET-118), mirroring READ_ONLY_TOOLS/_is_dangerous. Best-effort
    # default names — operators must align to their host's tool registry (frontend-bindable,
    # PET-112). PET-121 (D-NS): an MCP-namespaced egress tool must be listed by its FULL
    # single-underscore wire name (e.g. mcp_acme_send_email), not a bare name — the
    # single-underscore mcp_ prefix is ambiguous (the separator is also a legal name char)
    # and is deliberately NOT stripped; canonicalization then closes the case/homoglyph/
    # CamelCase/_tool variants OF THAT configured wire name. See docs/deployment/
    # hermes-desktop.md ("Tool-name canonicalization vs Hermes dispatch").
    egress_sink_tools: tuple[str, ...] = (
        "send_email",
        "send_message",
        "post_social",
        "http_request",
        "send_webhook",
        "clipboard_write",
    )
    # PET-134: source namespaces whose returned content taints (a content-agnostic
    # provenance fence layered over the PII-egress block). Stored RAW as
    # single-underscore wire prefixes (e.g. "mcp_bank_"); canonicalized by the plugin
    # through the SAME canonicalize_tool_name primitive the egress sinks use (PET-118),
    # then PREFIX-matched against a producing tool's canonical name (D-NS). Empty (the
    # default) disables the fence entirely, exactly as an empty egress_sink_tools
    # disables egress PII blocking. Validated identically to egress_sink_tools (bare-str
    # reject, list->tuple coerce, per-entry non-empty, empty allowed). No
    # banking-specific names ship — this is a reusable Petasos primitive.
    source_taint_namespaces: tuple[str, ...] = ()
    # PET-134: the false-positive floor — a tainted span shorter than this (measured on
    # the NORMALIZED span) is never stored, so low-entropy values ("$5.00", "2026")
    # cannot poison every later argument. Operator-tunable (FP is the single biggest
    # usability risk) without a code change; positive-int, mirrors lineage_max_edges.
    taint_min_span_length: int = 12

    def __post_init__(self) -> None:
        for fname in _BOOL_FIELDS:
            val = getattr(self, fname)
            if not isinstance(val, bool):
                raise TypeError(f"{fname} must be a bool, got {val!r}")
        if not isinstance(self.pii_entities, tuple):
            object.__setattr__(self, "pii_entities", tuple(self.pii_entities))
        if self.direction not in ("inbound", "outbound"):
            raise ValueError(f"direction must be 'inbound' or 'outbound', got {self.direction!r}")
        if self.fail_mode not in ("open", "closed", "degraded"):
            raise ValueError(
                f"fail_mode must be 'open', 'closed', or 'degraded', got {self.fail_mode!r}"
            )
        if self.redaction_mode not in ("redact", "replace", "hash", "mask"):
            raise ValueError(
                f"redaction_mode must be 'redact', 'replace', 'hash', or 'mask', "
                f"got {self.redaction_mode!r}"
            )
        if self.anonymize and self.redaction_mode == "hash" and not self.hash_key:
            raise ValueError(
                "hash_key is required and must be non-empty when "
                "redaction_mode='hash' and anonymize=True"
            )
        for entity in self.pii_entities:
            if not isinstance(entity, str) or not entity.strip():
                raise ValueError(
                    f"pii_entities entries must be non-empty, non-whitespace strings, "
                    f"got {entity!r}"
                )
        # Trim surrounding whitespace so a " EMAIL_ADDRESS " entry isn't a silent no-op in
        # the Stage 9 anonymize filter (which matches on the uppercased entity type, D7).
        object.__setattr__(self, "pii_entities", tuple(e.strip() for e in self.pii_entities))

        # Presidio detection scoping (PET-109). presidio_entities: None = use the
        # scanner default; an explicit value replaces it wholesale (mirrors the
        # delegate_tool_names template — bare-str reject, list→tuple coerce, per-entry
        # check — with a None early-out and an empty-tuple reject prepended).
        if self.presidio_entities is not None:
            if isinstance(self.presidio_entities, str):
                raise ValueError(
                    "presidio_entities must be an iterable of entity names, not a string, "
                    f"got {self.presidio_entities!r}"
                )
            if not isinstance(self.presidio_entities, tuple):
                object.__setattr__(self, "presidio_entities", tuple(self.presidio_entities))
            if not self.presidio_entities:  # empty explicit tuple is meaningless
                raise ValueError(
                    "presidio_entities must be non-empty when not None (use None for default)"
                )
            for e in self.presidio_entities:
                if not isinstance(e, str) or not e.strip():
                    raise ValueError(
                        f"presidio_entities entries must be non-empty, non-whitespace strings, "
                        f"got {e!r}"
                    )
            # Trim, then normalize to Presidio's case-sensitive uppercase vocabulary so a
            # lowercase/typo/whitespace entry (e.g. "person", " URL ") isn't a silent no-op
            # (it would match nothing in analyzer.analyze).
            object.__setattr__(
                self,
                "presidio_entities",
                tuple(e.strip().upper() for e in self.presidio_entities),
            )

        # presidio_entities_extra: additive opt-ins; empty () is the default and is
        # allowed (no None early-out, no empty reject). The bare-str reject is
        # load-bearing here too: tuple("URL") -> ("U","R","L") would pass the
        # per-entry check and become three no-op recognizer names.
        if isinstance(self.presidio_entities_extra, str):
            raise ValueError(
                "presidio_entities_extra must be an iterable of entity names, not a string, "
                f"got {self.presidio_entities_extra!r}"
            )
        if not isinstance(self.presidio_entities_extra, tuple):
            object.__setattr__(
                self, "presidio_entities_extra", tuple(self.presidio_entities_extra)
            )
        for e in self.presidio_entities_extra:
            if not isinstance(e, str) or not e.strip():
                raise ValueError(
                    f"presidio_entities_extra entries must be non-empty, non-whitespace strings, "
                    f"got {e!r}"
                )
        object.__setattr__(
            self,
            "presidio_entities_extra",
            tuple(e.strip().upper() for e in self.presidio_entities_extra),
        )

        # presidio_score_threshold: finite and inclusive [0.0, 1.0]. 0.0 is the
        # documented power-user "all candidates" escape hatch.
        if not math.isfinite(self.presidio_score_threshold) or not (
            0.0 <= self.presidio_score_threshold <= 1.0
        ):
            raise ValueError(
                f"presidio_score_threshold must be finite and in [0.0, 1.0], "
                f"got {self.presidio_score_threshold!r}"
            )

        # Scanner timeout + circuit breaker validation (PIPE-03)
        if self.scanner_timeout_seconds <= 0 or not math.isfinite(self.scanner_timeout_seconds):
            raise ValueError(
                f"scanner_timeout_seconds must be positive and finite, "
                f"got {self.scanner_timeout_seconds!r}"
            )
        if self.scanner_timeout_seconds > 60.0:
            raise ValueError(
                f"scanner_timeout_seconds must be <= 60, got {self.scanner_timeout_seconds!r}"
            )
        if (
            not isinstance(self.scanner_circuit_breaker_threshold, int)
            or isinstance(self.scanner_circuit_breaker_threshold, bool)
            or self.scanner_circuit_breaker_threshold <= 0
        ):
            raise ValueError(
                f"scanner_circuit_breaker_threshold must be a positive integer, "
                f"got {self.scanner_circuit_breaker_threshold!r}"
            )
        if self.scanner_circuit_breaker_cooldown_seconds <= 0 or not math.isfinite(
            self.scanner_circuit_breaker_cooldown_seconds
        ):
            raise ValueError(
                f"scanner_circuit_breaker_cooldown_seconds must be positive and finite, "
                f"got {self.scanner_circuit_breaker_cooldown_seconds!r}"
            )

        # Premium field validation
        if self.frequency_half_life_seconds <= 0 or not math.isfinite(
            self.frequency_half_life_seconds
        ):
            raise ValueError(
                f"frequency_half_life_seconds must be positive and finite, "
                f"got {self.frequency_half_life_seconds!r}"
            )
        if self.rolling_window_seconds <= 0 or not math.isfinite(self.rolling_window_seconds):
            raise ValueError(
                f"rolling_window_seconds must be positive and finite, "
                f"got {self.rolling_window_seconds!r}"
            )
        if not isinstance(self.rolling_threshold, int) or self.rolling_threshold <= 0:
            raise ValueError(
                f"rolling_threshold must be a positive integer, got {self.rolling_threshold!r}"
            )
        _validate_tier_thresholds(self.tier1_threshold, self.tier2_threshold, self.tier3_threshold)
        if not isinstance(self.max_sessions, int) or self.max_sessions <= 0:
            raise ValueError(f"max_sessions must be a positive integer, got {self.max_sessions!r}")
        if self.session_ttl_seconds <= 0 or not math.isfinite(self.session_ttl_seconds):
            raise ValueError(
                f"session_ttl_seconds must be positive and finite, "
                f"got {self.session_ttl_seconds!r}"
            )
        if (
            not isinstance(self.max_new_sessions_per_minute, int)
            or self.max_new_sessions_per_minute <= 0
        ):
            raise ValueError(
                f"max_new_sessions_per_minute must be a positive integer, "
                f"got {self.max_new_sessions_per_minute!r}"
            )
        if (
            not isinstance(self.max_terminated_tombstones, int)
            or isinstance(self.max_terminated_tombstones, bool)
            or self.max_terminated_tombstones <= 0
        ):
            raise ValueError(
                f"max_terminated_tombstones must be a positive integer, "
                f"got {self.max_terminated_tombstones!r}"
            )
        if self.session_secret is not None and not isinstance(self.session_secret, bytes):
            raise ValueError(
                f"session_secret must be bytes or None, got {type(self.session_secret).__name__}"
            )

        # Sub-agent session intelligence validation (PET-107)
        if (
            not isinstance(self.lineage_max_depth, int)
            or isinstance(self.lineage_max_depth, bool)
            or self.lineage_max_depth <= 0
        ):
            raise ValueError(
                f"lineage_max_depth must be a positive integer, got {self.lineage_max_depth!r}"
            )
        if (
            not isinstance(self.lineage_max_edges, int)
            or isinstance(self.lineage_max_edges, bool)
            or self.lineage_max_edges <= 0
        ):
            raise ValueError(
                f"lineage_max_edges must be a positive integer, got {self.lineage_max_edges!r}"
            )
        if self.lineage_edge_ttl_seconds <= 0 or not math.isfinite(self.lineage_edge_ttl_seconds):
            raise ValueError(
                f"lineage_edge_ttl_seconds must be positive and finite, "
                f"got {self.lineage_edge_ttl_seconds!r}"
            )
        if (
            not isinstance(self.delegate_max_fanout_per_window, int)
            or isinstance(self.delegate_max_fanout_per_window, bool)
            or self.delegate_max_fanout_per_window <= 0
        ):
            raise ValueError(
                f"delegate_max_fanout_per_window must be a positive integer, "
                f"got {self.delegate_max_fanout_per_window!r}"
            )
        if self.delegate_fanout_window_seconds <= 0 or not math.isfinite(
            self.delegate_fanout_window_seconds
        ):
            raise ValueError(
                f"delegate_fanout_window_seconds must be positive and finite, "
                f"got {self.delegate_fanout_window_seconds!r}"
            )
        # delegate_tool_names stored raw; coerce list→tuple in lockstep with
        # pii_entities so a to_dict/from_dict round-trip preserves the tuple type.
        # Reject a bare string first: tuple("delegate_task") would explode into
        # per-character entries that each pass the non-empty-string check below,
        # silently emptying the delegate match set and bypassing the spawn gate.
        if isinstance(self.delegate_tool_names, str):
            raise ValueError(
                "delegate_tool_names must be an iterable of tool names, not a string, "
                f"got {self.delegate_tool_names!r}"
            )
        if not isinstance(self.delegate_tool_names, tuple):
            try:
                object.__setattr__(self, "delegate_tool_names", tuple(self.delegate_tool_names))
            except TypeError as exc:
                raise ValueError(
                    f"delegate_tool_names must be an iterable of non-empty strings, "
                    f"got {self.delegate_tool_names!r}"
                ) from exc
        for tool_name in self.delegate_tool_names:
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError(
                    f"delegate_tool_names entries must be non-empty strings, got {tool_name!r}"
                )
        # egress_sink_tools (PET-112): RAW tool names, canonicalized by the plugin's
        # _is_egress_sink before matching (PET-118). Mirrors the delegate_tool_names
        # template — bare-str reject
        # (tuple("send_email") would char-explode and silently empty the set),
        # list→tuple coerce, per-entry non-empty check — but an EMPTY tuple is allowed
        # (an operator may disable egress PII blocking entirely; the plugin warns).
        if isinstance(self.egress_sink_tools, str):
            raise ValueError(
                "egress_sink_tools must be an iterable of tool names, not a string, "
                f"got {self.egress_sink_tools!r}"
            )
        if not isinstance(self.egress_sink_tools, tuple):
            try:
                object.__setattr__(self, "egress_sink_tools", tuple(self.egress_sink_tools))
            except TypeError as exc:
                raise ValueError(
                    f"egress_sink_tools must be an iterable of non-empty strings, "
                    f"got {self.egress_sink_tools!r}"
                ) from exc
        for tool_name in self.egress_sink_tools:
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError(
                    f"egress_sink_tools entries must be non-empty strings, got {tool_name!r}"
                )
        # source_taint_namespaces (PET-134): RAW namespace prefixes, canonicalized +
        # prefix-matched by the plugin. Validated with the egress_sink_tools template —
        # bare-str reject (tuple("mcp_bank_") would char-explode and silently empty the
        # set), list→tuple coerce, per-entry non-empty — and an EMPTY tuple is the default
        # (= fence off; the plugin warns when a non-empty config canonicalizes away).
        if isinstance(self.source_taint_namespaces, str):
            raise ValueError(
                "source_taint_namespaces must be an iterable of namespace prefixes, "
                f"not a string, got {self.source_taint_namespaces!r}"
            )
        if not isinstance(self.source_taint_namespaces, tuple):
            try:
                object.__setattr__(
                    self, "source_taint_namespaces", tuple(self.source_taint_namespaces)
                )
            except TypeError as exc:
                raise ValueError(
                    f"source_taint_namespaces must be an iterable of non-empty strings, "
                    f"got {self.source_taint_namespaces!r}"
                ) from exc
        for ns in self.source_taint_namespaces:
            if not isinstance(ns, str) or not ns:
                raise ValueError(
                    f"source_taint_namespaces entries must be non-empty strings, got {ns!r}"
                )
        # taint_min_span_length (PET-134): the FP floor — positive int, mirroring
        # lineage_max_edges (bool excluded; True/False is not a valid length).
        if (
            not isinstance(self.taint_min_span_length, int)
            or isinstance(self.taint_min_span_length, bool)
            or self.taint_min_span_length <= 0
        ):
            raise ValueError(
                f"taint_min_span_length must be a positive integer, "
                f"got {self.taint_min_span_length!r}"
            )
        if self.frequency_weights is not None:
            for k, v in self.frequency_weights.items():
                if not isinstance(k, str) or not k:
                    raise ValueError(
                        f"frequency_weights keys must be non-empty strings, got {k!r}"
                    )
                if v < 0 or not math.isfinite(v):
                    raise ValueError(
                        f"frequency_weights values must be non-negative and finite, "
                        f"got {k!r}: {v!r}"
                    )
            object.__setattr__(
                self, "frequency_weights", MappingProxyType(dict(self.frequency_weights))
            )

        # Alerting field validation
        if self.alert_cooldown_seconds <= 0 or not math.isfinite(self.alert_cooldown_seconds):
            raise ValueError(
                f"alert_cooldown_seconds must be positive and finite, "
                f"got {self.alert_cooldown_seconds!r}"
            )
        if (
            not isinstance(self.alert_per_minute_cap, int)
            or isinstance(self.alert_per_minute_cap, bool)
            or self.alert_per_minute_cap <= 0
        ):
            raise ValueError(
                f"alert_per_minute_cap must be a positive integer, "
                f"got {self.alert_per_minute_cap!r}"
            )
        if (
            not isinstance(self.alert_per_hour_cap, int)
            or isinstance(self.alert_per_hour_cap, bool)
            or self.alert_per_hour_cap <= 0
        ):
            raise ValueError(
                f"alert_per_hour_cap must be a positive integer, got {self.alert_per_hour_cap!r}"
            )
        if (
            not isinstance(self.alert_critical_per_minute_cap, int)
            or isinstance(self.alert_critical_per_minute_cap, bool)
            or self.alert_critical_per_minute_cap <= 0
        ):
            raise ValueError(
                f"alert_critical_per_minute_cap must be a positive integer, "
                f"got {self.alert_critical_per_minute_cap!r}"
            )
        if self.alert_high_severity_threshold not in (
            "critical",
            "high",
            "medium",
            "low",
            "info",
        ):
            raise ValueError(
                f"alert_high_severity_threshold must be one of "
                f"'critical', 'high', 'medium', 'low', 'info', "
                f"got {self.alert_high_severity_threshold!r}"
            )
        if (
            not isinstance(self.alert_rapid_fire_count, int)
            or isinstance(self.alert_rapid_fire_count, bool)
            or self.alert_rapid_fire_count <= 0
        ):
            raise ValueError(
                f"alert_rapid_fire_count must be a positive integer, "
                f"got {self.alert_rapid_fire_count!r}"
            )
        if self.alert_rapid_fire_window_seconds <= 0 or not math.isfinite(
            self.alert_rapid_fire_window_seconds
        ):
            raise ValueError(
                f"alert_rapid_fire_window_seconds must be positive and finite, "
                f"got {self.alert_rapid_fire_window_seconds!r}"
            )
        if (
            not isinstance(self.alert_cross_session_burst_count, int)
            or isinstance(self.alert_cross_session_burst_count, bool)
            or self.alert_cross_session_burst_count <= 0
        ):
            raise ValueError(
                f"alert_cross_session_burst_count must be a positive integer, "
                f"got {self.alert_cross_session_burst_count!r}"
            )
        if self.alert_cross_session_burst_window_seconds <= 0 or not math.isfinite(
            self.alert_cross_session_burst_window_seconds
        ):
            raise ValueError(
                f"alert_cross_session_burst_window_seconds must be positive and finite, "
                f"got {self.alert_cross_session_burst_window_seconds!r}"
            )
        if (
            not isinstance(self.alert_pii_volume_threshold, int)
            or isinstance(self.alert_pii_volume_threshold, bool)
            or self.alert_pii_volume_threshold <= 0
        ):
            raise ValueError(
                f"alert_pii_volume_threshold must be a positive integer, "
                f"got {self.alert_pii_volume_threshold!r}"
            )
        if self.alert_pii_volume_window_seconds <= 0 or not math.isfinite(
            self.alert_pii_volume_window_seconds
        ):
            raise ValueError(
                f"alert_pii_volume_window_seconds must be positive and finite, "
                f"got {self.alert_pii_volume_window_seconds!r}"
            )
        if (
            not isinstance(self.alert_ring_buffer_capacity, int)
            or isinstance(self.alert_ring_buffer_capacity, bool)
            or self.alert_ring_buffer_capacity <= 0
        ):
            raise ValueError(
                f"alert_ring_buffer_capacity must be a positive integer, "
                f"got {self.alert_ring_buffer_capacity!r}"
            )
        if self.alert_rapid_fire_count > self.alert_ring_buffer_capacity:
            raise ValueError(
                f"alert_rapid_fire_count ({self.alert_rapid_fire_count}) must be "
                f"<= alert_ring_buffer_capacity ({self.alert_ring_buffer_capacity})"
            )
        if self.alert_cross_session_burst_count > self.alert_ring_buffer_capacity:
            raise ValueError(
                f"alert_cross_session_burst_count "
                f"({self.alert_cross_session_burst_count}) must be "
                f"<= alert_ring_buffer_capacity "
                f"({self.alert_ring_buffer_capacity})"
            )
        if (
            not isinstance(self.alert_per_session_contribution_cap, int)
            or isinstance(self.alert_per_session_contribution_cap, bool)
            or self.alert_per_session_contribution_cap <= 0
        ):
            raise ValueError(
                f"alert_per_session_contribution_cap must be a positive integer, "
                f"got {self.alert_per_session_contribution_cap!r}"
            )
        if (
            not isinstance(self.alert_max_session_contribution_entries, int)
            or isinstance(self.alert_max_session_contribution_entries, bool)
            or self.alert_max_session_contribution_entries <= 0
        ):
            raise ValueError(
                f"alert_max_session_contribution_entries must be a positive integer, "
                f"got {self.alert_max_session_contribution_entries!r}"
            )
        if self.alert_per_session_contribution_cap > self.alert_per_minute_cap:
            raise ValueError(
                f"alert_per_session_contribution_cap ({self.alert_per_session_contribution_cap}) "
                f"must be <= alert_per_minute_cap ({self.alert_per_minute_cap})"
            )
        if self.audit_verbosity not in ("minimal", "standard", "verbose"):
            raise ValueError(
                f"audit_verbosity must be 'minimal', 'standard', or 'verbose', "
                f"got {self.audit_verbosity!r}"
            )

    def to_dict(self, *, redact_secrets: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for f in fields(self):
            if f.name == "session_secret":
                continue
            val = getattr(self, f.name)
            if redact_secrets and f.name in _SECRET_FIELDS:
                d[f.name] = "[REDACTED]" if val is not None else None
                continue
            if isinstance(val, tuple):
                val = list(val)
            elif isinstance(val, MappingProxyType):
                val = dict(val)
            d[f.name] = val
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PetasosConfig:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        if "pii_entities" in filtered and isinstance(filtered["pii_entities"], list):
            filtered["pii_entities"] = tuple(filtered["pii_entities"])
        if "delegate_tool_names" in filtered and isinstance(filtered["delegate_tool_names"], list):
            filtered["delegate_tool_names"] = tuple(filtered["delegate_tool_names"])
        if "egress_sink_tools" in filtered and isinstance(filtered["egress_sink_tools"], list):
            filtered["egress_sink_tools"] = tuple(filtered["egress_sink_tools"])
        # PET-134: list→tuple in lockstep with egress_sink_tools so a to_dict/from_dict
        # round-trip preserves the tuple type (the dataclass is frozen + tuple-typed).
        if "source_taint_namespaces" in filtered and isinstance(
            filtered["source_taint_namespaces"], list
        ):
            filtered["source_taint_namespaces"] = tuple(filtered["source_taint_namespaces"])
        # PET-109: coerce only when a list — preserve None so the None round-trip holds.
        if "presidio_entities" in filtered and isinstance(filtered["presidio_entities"], list):
            filtered["presidio_entities"] = tuple(filtered["presidio_entities"])
        if "presidio_entities_extra" in filtered and isinstance(
            filtered["presidio_entities_extra"], list
        ):
            filtered["presidio_entities_extra"] = tuple(filtered["presidio_entities_extra"])
        if "session_secret" in filtered and isinstance(filtered["session_secret"], str):
            import base64

            try:
                filtered["session_secret"] = base64.b64decode(filtered["session_secret"])
            except Exception:
                raise ValueError("session_secret must be valid base64") from None
        for key in _BOOL_FIELDS:
            if key in filtered and not isinstance(filtered[key], bool):
                raise TypeError(f"{key} must be a bool, got {filtered[key]!r}")
        return cls(**filtered)

    def copy(self) -> PetasosConfig:
        return self.from_dict(self.to_dict())
