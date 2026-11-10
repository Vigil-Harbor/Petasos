"""Session memory: frequency, escalation, audit, alerts, and how many sessions are kept."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from petasos.config.floors import TIER3_FLOOR
from petasos.config.schema import ConfigError, section, setting

_SEVERITY = Literal["critical", "high", "medium", "low", "info"]


@section
class FrequencyConfig:
    """The running risk score for one conversation, and how fast it fades."""

    enabled: bool = setting(
        default=True,
        help="Keep a running risk score per conversation so repeated trouble adds up.",
    )
    half_life_seconds: float = setting(
        default=60.0,
        gt=0,
        help="How many quiet seconds it takes for a conversation's risk score to fall by half.",
    )
    weights: Mapping[str, float] | None = setting(
        default=None,
        ge=0,
        help="How many points each rule adds, or leave unset to use the built-in weights.",
    )
    rolling_window_seconds: float = setting(
        default=300.0,
        gt=0,
        help="How many recent seconds of flagged scans count toward the slow-drip check.",
    )
    rolling_threshold: int = setting(
        default=10,
        gt=0,
        help="How many flagged scans in that window mark a conversation for extra scrutiny.",
    )

    def check(self) -> None:
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
    """The risk scores at which a conversation is watched, blocked, and then ended.

    The three scores must rise, and the last one cannot go below the tier-3 floor.
    """

    enabled: bool = setting(
        default=True,
        help="Report the conversation's escalation tier on each scan.",
    )
    tier1: float = setting(
        default=15.0,
        help="Risk score at which a conversation gets warnings but tool calls still run.",
    )
    tier2: float = setting(
        default=30.0,
        help="Risk score at which tool calls are blocked unless a tool is exempt.",
    )
    tier3: float = setting(
        default=50.0,
        ge=TIER3_FLOOR,
        help="Risk score at which the conversation is ended and stays ended.",
    )

    def check(self) -> None:
        if not self.tier1 < self.tier2 < self.tier3:
            raise ConfigError("must be strictly ascending: tier 1, then tier 2, then tier 3")


@section
class AuditConfig:
    """The record written for each scan."""

    enabled: bool = setting(
        default=True,
        help="Write an audit record for every scan so decisions can be reviewed later.",
    )
    verbosity: Literal["minimal", "standard", "verbose"] = setting(
        default="standard",
        help="How much each audit record carries: a verdict, findings, or full scanner output.",
    )
    emit_findings: bool = setting(
        default=False,
        help="Also write one log line per finding, for a short false-positive capture window.",
    )


@section
class AlertingConfig:
    """Warnings for bursts, spikes, and repeated findings.

    The caps and windows are expert settings. One session cannot spend the
    whole per-minute allowance, and a burst count cannot exceed the memory
    that holds recent events.
    """

    enabled: bool = setting(
        default=True,
        help="Watch for suspicious patterns and fire a warning when one appears.",
    )
    cooldown_seconds: float = setting(
        default=60.0,
        gt=0,
        audience="expert",
        help="How many seconds before the same warning can fire again for one conversation.",
    )
    per_minute_cap: int = setting(
        default=5,
        gt=0,
        audience="expert",
        help="The most times one warning may fire per minute across all conversations.",
    )
    per_hour_cap: int = setting(
        default=20,
        gt=0,
        audience="expert",
        help="The most times one warning may fire per hour, the long-term ceiling.",
    )
    critical_per_minute_cap: int = setting(
        default=20,
        gt=0,
        audience="expert",
        help="The per-minute allowance for critical warnings, which skip the quieter caps.",
    )
    high_severity_threshold: _SEVERITY = setting(
        default="high",
        audience="expert",
        help="The least serious finding that still fires the high-severity warning.",
    )
    rapid_fire_count: int = setting(
        default=10,
        gt=0,
        audience="expert",
        help="How many unsafe scans from one conversation, inside the window, count as a burst.",
    )
    rapid_fire_window_seconds: float = setting(
        default=60.0,
        gt=0,
        audience="expert",
        help="How many seconds of one conversation are counted for the rapid-fire warning.",
    )
    cross_session_burst_count: int = setting(
        default=3,
        gt=0,
        audience="expert",
        help="How many conversations must show findings before a coordinated burst is warned.",
    )
    cross_session_burst_window_seconds: float = setting(
        default=60.0,
        gt=0,
        audience="expert",
        help="How many seconds are counted when looking for findings across many conversations.",
    )
    pii_volume_threshold: int = setting(
        default=20,
        gt=0,
        audience="expert",
        help="How many personal-information findings in the window count as a leak spike.",
    )
    pii_volume_window_seconds: float = setting(
        default=300.0,
        gt=0,
        audience="expert",
        help="How many seconds of personal-information findings count toward the leak warning.",
    )
    ring_buffer_capacity: int = setting(
        default=1000,
        gt=0,
        audience="expert",
        help="How many recent events the warnings remember; burst counts must fit inside it.",
    )
    per_session_contribution_cap: int = setting(
        default=2,
        gt=0,
        audience="expert",
        help="The most warnings one conversation may contribute per rule per minute.",
    )
    max_session_contribution_entries: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        help="How many conversation-and-rule pairs the fairness tracking can follow at once.",
    )

    def check(self) -> None:
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
    """How many conversations are remembered, and for how long."""

    max: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        help="The most conversations tracked at once; the oldest finished ones are dropped first.",
    )
    ttl_seconds: float = setting(
        default=3600.0,
        gt=0,
        audience="expert",
        help="How many seconds an idle conversation stays tracked before it can be forgotten.",
    )
    max_new_per_minute: int = setting(
        default=60,
        gt=0,
        audience="expert",
        help="How many new conversations may start per minute once the store is already full.",
    )
    max_tombstones: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        help="How many ended conversations to remember so the same id cannot start clean.",
    )


@section
class StartupConfig:
    """How long a tool call waits while scanners are still starting."""

    wait_seconds: float = setting(
        default=2.0,
        gt=0,
        le=60,
        help="How many seconds a tool call waits for scanners to load before the fast check.",
    )
