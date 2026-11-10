"""Plain sentences for findings and enforcement events.

The technical id follows in the structured fields. These sentences are what
a person reads.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOOKS_FOR = MappingProxyType(
    {
        "ignore-previous": "Looks for text that tells the agent to ignore earlier instructions.",
        "ignore-all": "Looks for text that tells the agent to ignore all of its instructions.",
        "disregard": (
            "Looks for text that tells the agent to disregard or forget its instructions."
        ),
        "new-instructions": "Looks for text that announces a new set of instructions.",
        "system-override": "Looks for text that pretends to be a system override.",
        "system-prefix": "Looks for text that imitates a system prompt.",
        "inst-delimiter": "Looks for fake instruction markers.",
        "you-are-now": "Looks for text that tells the agent it is now something else.",
        "role-switch-capability": "Looks for a role change that also grants new abilities.",
        "role-switch-only": "Looks for text that tells the agent to take on another role.",
        "agent-directed-fetch": (
            "Looks for instructions telling the agent to fetch or install something."
        ),
        "pipe-to-shell": "Looks for a command piped into a shell.",
        "decode-exec": "Looks for a command that decodes hidden text and runs it.",
        "fetch-exec": "Looks for a command that downloads a script and runs it.",
        "alias-escape": "Looks for a command that hides a dangerous verb behind a backslash.",
        "destructive-recursive": "Looks for a shell command that would delete files recursively.",
        "invisible-chars": "Looks for hidden characters that a person would not see.",
        "base64-in-text": "Looks for a long encoded block hidden in ordinary text.",
        "homoglyph-substitution": "Looks for letters swapped for look-alike characters.",
        "rtl-override": "Looks for characters that reverse the direction of the text.",
        "injection": "Looks for a prompt-injection pattern.",
    }
)


def looks_for(rule_id: str, message: str) -> str:
    """One sentence for what ``rule_id`` matches. ``message`` is the fallback."""
    slug = rule_id.rsplit(".", 1)[-1]
    known = _LOOKS_FOR.get(slug)
    if known is not None:
        return known
    text = message.strip()
    if not text:
        return "This rule matched."
    if text.endswith("."):
        return text
    return text + "."


def describe_event(event: Mapping[str, object]) -> str:
    """One sentence for what an enforcement event did."""
    kind = _text(event.get("event_type"))
    tool = _text(event.get("tool"))
    rule = _text(event.get("rule_id"))
    if rule.endswith("destructive-recursive"):
        return "Blocked a shell command that would delete files recursively."
    if kind in {"quarantine", "block"}:
        if tool in {"terminal", "execute_code"}:
            return "Blocked a shell command."
        if tool:
            return f"Blocked a {tool} call."
        return "Blocked a tool call."
    if kind == "tier3":
        return "Stopped every tool call because the session reached the highest risk level."
    if kind == "bypassed_disarmed":
        return "Let a tool call through because protection is paused, and recorded it."
    if kind == "init_failed":
        return "Used only the basic checks, because the scanners did not finish starting."
    if kind == "cold_start_degraded":
        return "Used only the basic checks, because the scanners were still starting."
    if kind == "selfmod_attempt":
        return "Recorded an attempt to change Petasos or Hermes settings."
    if kind == "ingest_flagged":
        return "Flagged a tool result that matched a rule, and passed the text on with a warning."
    if kind == "ingest_unscanned":
        return "Could not scan a tool result, and passed it on unmarked."
    if kind == "approval":
        phase = _text(event.get("phase"))
        if phase == "request":
            return "Asked for approval before a tool call."
        return "Recorded the answer to an approval ask."
    if tool:
        return f"Recorded a Petasos event for {tool}."
    return "Recorded a Petasos event."


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
