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
    """Text cleanup applied before the optional scanners see a scan."""

    nfkc: bool = setting(
        default=True,
        help="Rewrite stylized letters into plain text before the optional scanners see it.",
    )
    zero_width: bool = setting(
        default=True,
        help="Remove invisible characters that can hide instructions in ordinary-looking text.",
    )
    homoglyphs: bool = setting(
        default=True,
        help="Turn look-alike letters into plain equivalents before optional scanners see them.",
    )
    decode_payloads: bool = setting(
        default=True,
        help="Decode base64, hex, and ROT13 blobs and scan the plaintext for hidden instructions.",
    )


@section
class AnonymizationConfig:
    """What happens to personal information after a scanner has reported it."""

    enabled: bool = setting(
        default=False,
        help="Replace reported personal information with placeholders before the text goes on.",
    )
    entities: tuple[str, ...] = setting(
        default=(),
        help="Which reported types to hide, or leave empty to hide every type a scanner reported.",
    )
    mode: Literal["redact", "replace", "hash", "mask"] = setting(
        default="redact",
        help="Hide a match with a label, a number, a keyed hash, or by masking all but the end.",
    )


@section
class PetasosConfig:
    """The whole configuration tree.

    Constructing a value, or reading one from a mapping, applies every bound
    and every floor. ``enabled``, the role, and the level are not fields here.
    """

    fail_mode: Literal["open", "degraded", "closed"] = setting(
        default="degraded",
        help=(
            "When a scanner breaks: let the text through, block it, "
            "or block it and stop early on a critical hit."
        ),
    )
    direction: Literal["inbound", "outbound"] = setting(
        default="inbound",
        help=(
            "Treat text as coming in from the user, or going out from the agent, "
            "when a caller does not say."
        ),
    )
    normalization: NormalizationConfig = setting(
        default=NormalizationConfig(),
        help="Text cleanup applied before the optional scanners see a scan.",
    )
    scanners: ScannersConfig = setting(
        default=ScannersConfig(),
        help="How long a scanner may run, and the settings for each optional scanner.",
    )
    rules: RulesConfig = setting(
        default=RulesConfig(),
        help="Which findings are dropped, retargeted, or ignored for being too weak.",
    )
    anonymization: AnonymizationConfig = setting(
        default=AnonymizationConfig(),
        help="What happens to personal information after a scanner has reported it.",
    )
    frequency: FrequencyConfig = setting(
        default=FrequencyConfig(),
        help="The running risk score for one conversation.",
    )
    escalation: EscalationConfig = setting(
        default=EscalationConfig(),
        help="The scores at which a conversation is watched, blocked, and ended.",
    )
    tools: ToolsConfig = setting(
        default=ToolsConfig(),
        help="The tool-call guard and the limits on helper sub-agents.",
    )
    egress: EgressConfig = setting(
        default=EgressConfig(),
        help="Which tools send data out, and which returned text must not leave.",
    )
    audit: AuditConfig = setting(
        default=AuditConfig(),
        help="The record written for each scan.",
    )
    alerting: AlertingConfig = setting(
        default=AlertingConfig(),
        help="Warnings for bursts, spikes, and repeated findings.",
    )
    sessions: SessionsConfig = setting(
        default=SessionsConfig(),
        help="How many conversations are remembered, and for how long.",
    )
    startup: StartupConfig = setting(
        default=StartupConfig(),
        help="How long a tool call waits while scanners are still starting.",
    )
