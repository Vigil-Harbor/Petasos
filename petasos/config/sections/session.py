"""Session memory: frequency, escalation, audit, alerts, and how many sessions are kept."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from petasos.config.floors import TIER3_FLOOR
from petasos.config.schema import ConfigError, section, setting

_SEVERITY = Literal["critical", "high", "medium", "low", "info"]


@section
class FrequencyConfig:
    """Validate session risk decay and finding weights."""

    enabled: bool = setting(
        default=True,
        label="Keep a risk score",
        help="Keep a risk score for each conversation, so repeated trouble adds up.",
    )
    half_life_seconds: float = setting(
        default=60.0,
        gt=0,
        label="Score half-life (seconds)",
        help="How long a quiet conversation takes for its risk score to fall by half.",
    )
    weights: Mapping[str, float] | None = setting(
        default=None,
        ge=0,
        label="Points per rule",
        entry_labels=("Rule id or pattern", "Points"),
        help=(
            "How many points each rule adds to the risk score. Leave empty for the built-in "
            "points."
        ),
    )
    rolling_window_seconds: float = setting(
        default=300.0,
        gt=0,
        label="Slow-drip window (seconds)",
        help=(
            "The stretch of time over which small findings are counted, to catch an attack spread "
            "thinly."
        ),
    )
    rolling_threshold: int = setting(
        default=10,
        gt=0,
        label="Slow-drip limit",
        help="How many findings within that stretch put a conversation under closer watch.",
    )

    def check(self) -> None:
        """Reject wildcard weight keys unless the wildcard is a final dot-star."""
        if self.weights is None:
            return
        problems: list[tuple[str, str]] = []
        for key in self.weights:
            if key.endswith(".*"):
                if "*" in key[:-2]:
                    problems.append(
                        (f"weights.{key}", "a * is only allowed at the end, written as .*")
                    )
            elif "*" in key:
                problems.append(
                    (f"weights.{key}", "a * is only allowed at the end, written as .*")
                )
        if problems:
            raise ConfigError(problems)


@section
class EscalationConfig:
    """Validate ascending thresholds with an enforced termination floor.

    The three scores must rise, and the last one cannot go below the tier-3 floor."""

    enabled: bool = setting(
        default=True,
        label="Report the protection stage",
        help=(
            "Add the conversation's stage to each check result: normal, watched, tool calls"
            " blocked, or stopped."
        ),
    )
    tier1: float = setting(
        default=15.0,
        label="Warn at",
        help="At this risk score the conversation is watched more closely. Tool calls still run.",
    )
    tier2: float = setting(
        default=30.0,
        label="Block tool calls at",
        help="At this risk score tool calls are blocked, except tools allowed while blocked.",
    )
    tier3: float = setting(
        default=50.0,
        ge=TIER3_FLOOR,
        label="Stop the conversation at",
        help=(
            "At this risk score the conversation is stopped: every tool call in it, and in its"
            " helper agents, is blocked until Hermes restarts. Start a new conversation to carry"
            " on. It cannot be set below 30, so a hijacked conversation can always be stopped."
        ),
    )

    def check(self) -> None:
        """Require strictly increasing escalation thresholds."""
        if not self.tier1 < self.tier2 < self.tier3:
            raise ConfigError("must be strictly ascending: tier 1, then tier 2, then tier 3")


@section
class AuditConfig:
    """Validate audit activation, verbosity and finding emission."""

    enabled: bool = setting(
        default=True,
        label="Keep a record",
        help="Write down every check, so decisions can be reviewed later.",
    )
    verbosity: Literal["minimal", "standard", "verbose"] = setting(
        default="standard",
        label="Detail",
        help="How much each record holds.",
        choice_labels={
            "minimal": "The decision only",
            "standard": "The decision and what was found",
            "verbose": "Everything, including each check's full output",
        },
    )
    emit_findings: bool = setting(
        default=False,
        label="Log every finding",
        help=(
            "Also write one log line per finding. Useful for a short while when tracking down "
            "false alarms."
        ),
    )


@section
class AlertingConfig:
    """Validate alert windows, rate caps and buffer capacities.

    The caps and windows are expert settings. One session cannot spend the
    whole per-minute allowance, and a burst count cannot exceed the memory
    that holds recent events."""

    enabled: bool = setting(
        default=True,
        label="Warnings",
        help="Watch for suspicious patterns and raise a warning when one appears.",
    )
    cooldown_seconds: float = setting(
        default=60.0,
        gt=0,
        audience="expert",
        label="Repeat delay (seconds)",
        help="How long before the same warning can be raised again for one conversation.",
    )
    per_minute_cap: int = setting(
        default=5,
        gt=0,
        audience="expert",
        label="Per-minute limit",
        help="The most times one warning may be raised per minute, across all conversations.",
    )
    per_hour_cap: int = setting(
        default=20,
        gt=0,
        audience="expert",
        label="Per-hour limit",
        help="The most times one warning may be raised per hour.",
    )
    critical_per_minute_cap: int = setting(
        default=20,
        gt=0,
        audience="expert",
        label="Critical per-minute limit",
        help="The per-minute limit for critical warnings, which skip the other limits.",
    )
    high_severity_threshold: _SEVERITY = setting(
        default="high",
        audience="expert",
        label="Serious-finding warning from",
        help="The least serious finding that raises the serious-finding warning.",
        choice_labels={
            "critical": "Critical",
            "high": "High",
            "medium": "Medium",
            "low": "Low",
            "info": "Info",
        },
    )
    rapid_fire_count: int = setting(
        default=10,
        gt=0,
        audience="expert",
        label="Burst size",
        help=(
            "How many unsafe checks from one conversation, within the burst window, count as a "
            "burst."
        ),
    )
    rapid_fire_window_seconds: float = setting(
        default=60.0,
        gt=0,
        audience="expert",
        label="Burst window (seconds)",
        help="The stretch of time a burst is counted over.",
    )
    cross_session_burst_count: int = setting(
        default=3,
        gt=0,
        audience="expert",
        label="Conversations for a coordinated burst",
        help=(
            "How many conversations must show findings at once before a coordinated attack is "
            "warned about."
        ),
    )
    cross_session_burst_window_seconds: float = setting(
        default=60.0,
        gt=0,
        audience="expert",
        label="Coordinated burst window (seconds)",
        help="The stretch of time findings across conversations are counted over.",
    )
    pii_volume_threshold: int = setting(
        default=20,
        gt=0,
        audience="expert",
        label="Personal-detail spike size",
        help="How many personal-detail findings within the window count as a possible leak.",
    )
    pii_volume_window_seconds: float = setting(
        default=300.0,
        gt=0,
        audience="expert",
        label="Personal-detail spike window (seconds)",
        help="The stretch of time personal-detail findings are counted over.",
    )
    ring_buffer_capacity: int = setting(
        default=1000,
        gt=0,
        audience="expert",
        label="Events remembered",
        help="How many recent events the warnings remember. Burst sizes must fit inside it.",
    )
    per_session_contribution_cap: int = setting(
        default=2,
        gt=0,
        audience="expert",
        label="Per-conversation share",
        help="The most warnings one conversation may cause per rule per minute.",
    )
    max_session_contribution_entries: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        label="Fairness entries",
        help="How many conversation-and-rule pairs that share is tracked for at once.",
    )

    def check(self) -> None:
        """Reject alert limits that cannot fit their configured buffers."""
        problems: list[tuple[str, str]] = []
        if self.rapid_fire_count > self.ring_buffer_capacity:
            problems.append(
                ("rapid_fire_count", "must not be higher than the ring buffer capacity")
            )
        if self.cross_session_burst_count > self.ring_buffer_capacity:
            problems.append(
                ("cross_session_burst_count", "must not be higher than the ring buffer capacity")
            )
        if self.per_session_contribution_cap > self.per_minute_cap:
            problems.append(
                ("per_session_contribution_cap", "must not be higher than the per-minute cap")
            )
        if problems:
            raise ConfigError(problems)


@section
class SessionsConfig:
    """Validate retained-session bounds and expiry."""

    max: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        label="Most conversations tracked",
        help="The most conversations tracked at once. The oldest finished ones are dropped first.",
    )
    ttl_seconds: float = setting(
        default=3600.0,
        gt=0,
        audience="expert",
        label="Idle time before forgetting (seconds)",
        help="How long an idle conversation is kept before it can be forgotten.",
    )
    max_new_per_minute: int = setting(
        default=60,
        gt=0,
        audience="expert",
        label="New conversations per minute when full",
        help="How many new conversations may start per minute once the tracking is full.",
    )
    max_tombstones: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        label="Stopped conversations remembered",
        help=(
            "How many stopped conversations are remembered, so one cannot restart with a clean "
            "score."
        ),
    )


@section
class StartupConfig:
    """Validate how long tool calls wait for scanner startup."""

    wait_seconds: float = setting(
        default=2.0,
        gt=0,
        le=60,
        label="Startup wait (seconds)",
        help=(
            "How long a tool call waits for the checks to finish starting. After that, the basic "
            "checks decide alone."
        ),
    )
