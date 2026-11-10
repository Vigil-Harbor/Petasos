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
        label="Helpers inherit restrictions",
        help=(
            "A helper agent is at least as restricted as the conversation that "
            "launched it, so starting a helper cannot shake off a block."
        ),
    )
    max_depth: int = setting(
        default=8,
        gt=0,
        audience="expert",
        label="Generations to follow",
        help="How many generations of helpers to follow back when passing on a restriction.",
    )
    max_edges: int = setting(
        default=10_000,
        gt=0,
        audience="expert",
        label="Links remembered",
        help="How many helper-to-parent links Petasos remembers at once.",
    )
    edge_ttl_seconds: float = setting(
        default=3600.0,
        gt=0,
        audience="expert",
        label="Link lifetime (seconds)",
        help="How long a helper's link to the conversation that launched it is kept.",
    )


@section
class FanoutConfig:
    """How fast one conversation may launch helper sub-agents."""

    enabled: bool = setting(
        default=True,
        label="Limit helper launches",
        help="Limit how fast one conversation can launch helper agents.",
    )
    max_per_window: int = setting(
        default=3,
        gt=0,
        label="Helpers per window",
        help="How many helpers a calm conversation may launch within the window below.",
    )
    window_seconds: float = setting(
        default=60.0,
        gt=0,
        label="Window (seconds)",
        help="The length of time the helper limit is counted over.",
    )


@section
class ToolsConfig:
    """The tool-call guard: what it blocks, what it skips, and which names launch helpers.

    An alias must name a real tool, and it must not point at a tool that is exempt.
    """

    enabled: bool = setting(
        default=True,
        label="Check tool calls",
        help=(
            "Check each tool call before it runs, and block tool calls once a "
            "conversation's risk score is too high."
        ),
    )
    dangerous_posture: Literal["block", "approve"] = setting(
        default="block",
        label="When a dangerous action is found",
        help=(
            "What happens when a tool call that can change things, such as a shell "
            "command or a file write, matches a rule."
        ),
        choice_labels={
            "block": "Block it",
            "approve": "Ask a person for approval",
        },
    )
    exempt: tuple[str, ...] = setting(
        default=(),
        normalize=str.casefold,
        label="Tools allowed while the conversation is blocked",
        help=(
            "Tools that keep working after a conversation's tool calls are blocked. "
            "One tool name per line, such as web_search."
        ),
    )
    aliases: Mapping[str, str] = setting(
        default={},
        label="Other names for tools",
        help=(
            "When a tool is reachable under another name, map that name to the real "
            "tool so it is checked the same way. Written as other name and real name."
        ),
    )
    delegate_names: tuple[str, ...] = setting(
        default=("delegate_task",),
        label="Tools that launch helpers",
        help="Tools that start a helper agent. One tool name per line.",
    )
    lineage: LineageConfig = setting(
        default=LineageConfig(),
        label="Helper restrictions",
        help=(
            "Whether a helper agent inherits the restrictions of the conversation that launched "
            "it."
        ),
    )
    fanout: FanoutConfig = setting(
        default=FanoutConfig(),
        label="Helper launch limit",
        help="How fast one conversation may launch helper agents.",
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
        label="Tools that send data out",
        help=(
            "Tools that send content off the machine, such as email or a web request. One per "
            "line."
        ),
    )
    taint_namespaces: tuple[str, ...] = setting(
        default=(),
        label="Tools whose results must not leave",
        help=(
            "Tool name prefixes, one per line. Text these tools return is remembered, "
            "and a tool that sends data out is stopped if it tries to send that text."
        ),
    )
    taint_min_span_length: int = setting(
        default=12,
        gt=0,
        label="Shortest text remembered",
        help=(
            "The shortest piece of returned text, in characters, that is remembered, "
            "so a short value like a price or a year is not."
        ),
    )
