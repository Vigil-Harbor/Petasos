"""Tool-call guard, sub-agent limits, and the egress fence."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from petasos.config.schema import ConfigError, section, setting

_EGRESS_TOOLS = (
    "send_email",
    "send_message",
    "post_social",
    "http_request",
    "send_webhook",
    "clipboard_write",
)


@section
class LineageConfig:
    """Whether a child sub-agent inherits its parent's restriction."""

    enabled: bool = setting(
        default=True,
        help="Make a helper at least as restricted as the conversation that launched it.",
    )
    max_depth: int = setting(
        default=8,
        gt=0,
        audience="expert",
        help="How many parents up to walk when a sub-agent inherits a restriction.",
    )
    max_edges: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        help="How many parent-and-child links to remember at once.",
    )
    edge_ttl_seconds: float = setting(
        default=3600.0,
        gt=0,
        audience="expert",
        help="How many seconds a sub-agent's link to its parent stays valid.",
    )


@section
class FanoutConfig:
    """How fast one conversation may launch helper sub-agents."""

    enabled: bool = setting(
        default=True,
        help="Cap how fast one conversation can launch helper sub-agents.",
    )
    max_per_window: int = setting(
        default=3,
        gt=0,
        help="How many helpers a calm conversation may launch in the window.",
    )
    window_seconds: float = setting(
        default=60.0,
        gt=0,
        help="How many seconds that helper allowance is measured over.",
    )


@section
class ToolsConfig:
    """The tool-call guard: what it blocks, what it skips, and which names launch helpers.

    An alias must name a real tool, and it must not point at a tool that is exempt.
    """

    enabled: bool = setting(
        default=True,
        help="Check tool calls before they run, and block them once a conversation has escalated.",
    )
    dangerous_posture: Literal["block", "approve"] = setting(
        default="block",
        help="Block a dangerous tool call, or hand it to the host for approval.",
    )
    exempt: tuple[str, ...] = setting(
        default=(),
        normalize=str.casefold,
        help="Tool names that still run when a conversation is in the blocked tier.",
    )
    aliases: Mapping[str, str] = setting(
        default={},
        help="Extra names for a tool, so a variant is judged as the tool it really calls.",
    )
    delegate_names: tuple[str, ...] = setting(
        default=("delegate_task",),
        help="Tool names that count as launching a helper sub-agent.",
    )
    lineage: LineageConfig = setting(
        default=LineageConfig(),
        help="Whether a helper inherits its parent's restriction, and the bookkeeping limits.",
    )
    fanout: FanoutConfig = setting(
        default=FanoutConfig(),
        help="How fast one conversation may launch helpers.",
    )

    def check(self) -> None:
        problems: list[tuple[str, str]] = []
        cleaned: dict[str, str] = {}
        for key, value in self.aliases.items():
            stripped = value.strip()
            if stripped == "":
                problems.append((f"aliases.{key}", "must name a tool"))
            else:
                cleaned[key] = stripped
        if problems:
            raise ConfigError(problems)
        if any(cleaned[key] != self.aliases[key] for key in cleaned):
            object.__setattr__(self, "aliases", MappingProxyType(cleaned))
        collisions = sorted({value.casefold() for value in cleaned.values()} & set(self.exempt))
        if collisions:
            listed = ", ".join(collisions)
            raise ConfigError.at("aliases", f"must not point at an exempt tool: {listed}")


@section
class EgressConfig:
    """Which tools send data out, and which returned text must not leave."""

    sink_tools: tuple[str, ...] = setting(
        default=_EGRESS_TOOLS,
        help="Tool names that send content out, such as email or an external web request.",
    )
    taint_namespaces: tuple[str, ...] = setting(
        default=(),
        help="Name prefixes whose returned text must not later leave through an egress tool.",
    )
    taint_min_span_length: int = setting(
        default=12,
        gt=0,
        help="The shortest returned snippet the fence remembers, so a price or a year is ignored.",
    )
