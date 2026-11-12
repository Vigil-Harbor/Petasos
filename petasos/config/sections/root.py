"""The configuration tree. One declaration, checked on construction and on read."""

from __future__ import annotations

from typing import Literal

from petasos.config.schema import section, setting
from petasos.config.sections.rules import RulesConfig
from petasos.config.sections.scanners import ScannersConfig
from petasos.config.sections.session import (
    AlertingConfig,
    AuditConfig,
    EscalationConfig,
    FrequencyConfig,
    SessionsConfig,
    StartupConfig,
)
from petasos.config.sections.tools import EgressConfig, ToolsConfig


@section
class NormalizationConfig:
    """Validate independent text-normalization settings."""

    nfkc: bool = setting(
        default=True,
        label="Plain letters",
        help=(
            "Turn fancy or stylised letters into ordinary ones before the optional "
            "checks read the text, so a disguise does not hide a word."
        ),
    )
    zero_width: bool = setting(
        default=True,
        label="Remove invisible characters",
        help="Remove characters you cannot see, which can hide instructions inside normal text.",
    )
    homoglyphs: bool = setting(
        default=True,
        label="Look-alike letters",
        help=(
            "Swap look-alike letters, such as a Cyrillic a, for the ordinary letter "
            "before the optional checks read the text."
        ),
    )
    decode_payloads: bool = setting(
        default=True,
        label="Decode hidden text",
        help=(
            "Decode text hidden in base64, hex or ROT13 and check what it says for instructions."
        ),
    )


@section
class AnonymizationConfig:
    """Validate personal-information replacement settings."""

    enabled: bool = setting(
        default=False,
        label="Hide personal details",
        help=(
            "Replace personal details a check found, such as a name or a card number, "
            "with a placeholder before the text goes on."
        ),
    )
    entities: tuple[str, ...] = setting(
        default=(),
        label="Kinds to hide",
        help=(
            "Which kinds of personal detail to hide, one per line, such as "
            "EMAIL_ADDRESS. Leave empty to hide every kind that was found."
        ),
    )
    mode: Literal["redact", "replace", "hash", "mask"] = setting(
        default="redact",
        label="How to hide them",
        help="What a hidden detail turns into.",
        choice_labels={
            "redact": "A label, such as <EMAIL_ADDRESS>",
            "replace": "A numbered placeholder",
            "hash": "A keyed fingerprint (needs the hash key)",
            "mask": "Masked, keeping only the last few characters",
        },
    )


@section
class PetasosConfig:
    """Validate and freeze the complete scanner and policy configuration.

    Constructing a value, or reading one from a mapping, applies every bound
    and every floor. ``enabled``, the role, and the level are not fields here."""

    fail_mode: Literal["open", "degraded", "closed"] = setting(
        default="degraded",
        label="If a check breaks",
        help=(
            "What happens when an optional check crashes or times out. The basic "
            "checks always run either way."
        ),
        choice_labels={
            "open": "Let the text through",
            "degraded": "Block it",
            "closed": "Block it, and skip optional checks after a critical finding",
        },
    )
    direction: Literal["inbound", "outbound"] = setting(
        default="inbound",
        label="Assumed direction",
        help="Which way text is treated as moving when the caller does not say.",
        choice_labels={
            "inbound": "Coming in to the agent",
            "outbound": "Going out from the agent",
        },
    )
    normalization: NormalizationConfig = setting(
        default=NormalizationConfig(),
        label="Text cleanup",
        help="Undo common disguises before the optional checks read the text.",
    )
    scanners: ScannersConfig = setting(
        default=ScannersConfig(),
        label="Checks",
        help="How long a check may take, and the optional checks you can add.",
    )
    rules: RulesConfig = setting(
        default=RulesConfig(),
        label="Rules",
        help="Turn off a rule, change how serious it counts as, or ignore weak matches.",
    )
    anonymization: AnonymizationConfig = setting(
        default=AnonymizationConfig(),
        label="Personal details",
        help="Whether personal details a check finds are hidden before the text goes on.",
    )
    frequency: FrequencyConfig = setting(
        default=FrequencyConfig(),
        label="Risk score",
        help=(
            "Each finding adds points to the conversation's risk score, and the score "
            "fades when things are quiet."
        ),
    )
    escalation: EscalationConfig = setting(
        default=EscalationConfig(),
        label="Escalation",
        help=(
            "The risk scores at which a conversation is warned, has its tool calls "
            "blocked, and is stopped."
        ),
    )
    tools: ToolsConfig = setting(
        default=ToolsConfig(),
        label="Tool calls",
        help="What happens to a risky tool call, and the limits on helper agents.",
    )
    egress: EgressConfig = setting(
        default=EgressConfig(),
        label="Sending data out",
        help="Which tools send data out of the machine, and which text must not leave.",
    )
    audit: AuditConfig = setting(
        default=AuditConfig(),
        label="Record",
        help="What Petasos writes down about each check.",
    )
    alerting: AlertingConfig = setting(
        default=AlertingConfig(),
        label="Warnings",
        help="Warnings for bursts of activity, spikes, and repeated findings.",
    )
    sessions: SessionsConfig = setting(
        default=SessionsConfig(),
        label="Conversations",
        help="How many conversations Petasos keeps track of, and for how long.",
    )
    startup: StartupConfig = setting(
        default=StartupConfig(),
        label="Startup",
        help="How long a tool call waits while the checks are still starting.",
    )
