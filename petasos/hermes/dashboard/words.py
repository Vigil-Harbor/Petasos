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


# What a rule family looks for, as the end of a sentence ("contained ...").
_FAMILY = MappingProxyType(
    {
        "injection": "hidden instructions",
        "promptguard": "hidden instructions",
        "command": "a dangerous command",
        "encoding": "hidden or disguised text",
        "structural": "oversized or malformed input",
        "presidio": "personal information",
        "pii": "personal information",
        "semgrep": "risky code",
        "selfmod": "a change to Petasos or Hermes settings",
    }
)

# Plain names for event types, for a filter list. The type id follows in the data.
_KIND_LABELS = MappingProxyType(
    {
        "quarantine": "Blocked tool call",
        "block": "Blocked: conversation too risky",
        "tier3": "Conversation stopped",
        "approval": "Asked a person",
        "bypassed_disarmed": "Let through while paused",
        "selfmod_attempt": "Attempt to change the guardrails",
        "ingest_flagged": "Tool result flagged",
        "ingest_unscanned": "Tool result not checked",
        "init_failed": "Ran with basic checks only",
        "cold_start_degraded": "Ran with basic checks only",
    }
)

# Event types that mean the call they follow did not run.
_STOPPED_KINDS = frozenset({"quarantine", "block", "tier3"})

_DECLINED = frozenset({"deny", "denied", "timeout", "cancelled", "refused"})
_APPROVED = frozenset({"once", "session", "always", "approve", "approved", "allow"})


def rule_family(rule_id: str) -> str:
    """The family part of a rule id: ``petasos.syntactic.injection.x`` is ``injection``."""
    text = rule_id.removeprefix("plugin_rule:")
    parts = text.split(".")
    if len(parts) >= 3 and parts[0] == "petasos":
        if parts[1] in {"syntactic", "presidio", "semgrep"} and len(parts) >= 4:
            return parts[2] if parts[1] == "syntactic" else parts[1]
        return parts[1]
    return ""


def kind_label(kind: str) -> str:
    """A plain name for one event type. Unknown types are returned as they are."""
    return _KIND_LABELS.get(kind, kind)


def rule_sentence(rule_id: str) -> str:
    """What the rule behind an event looks for, or empty when there is no rule."""
    text = rule_id.removeprefix("plugin_rule:").strip()
    if not text:
        return ""
    slug = text.rsplit(".", 1)[-1]
    known = _LOOKS_FOR.get(slug)
    if known is not None:
        return known
    family = _FAMILY.get(rule_family(text))
    if family is not None:
        return f"Looks for {family}."
    return ""


def outcome(
    event: Mapping[str, object],
    follower: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """What Petasos did about an event: a stable ``code`` and a short ``label``.

    ``follower`` is the event Petasos wrote for the same tool call right after
    this one, when there is one. It decides what happened to a call that tried
    to change Petasos's or Hermes's own settings: recording that attempt does
    not stop the call by itself.
    """
    kind = _text(event.get("event_type"))
    if kind == "selfmod_attempt":
        then = _text(follower.get("event_type")) if follower is not None else ""
        # The block itself is its own event; these codes keep the call from
        # being counted twice among the blocks.
        if then in _STOPPED_KINDS:
            return {"code": "attempt_blocked", "label": "Blocked"}
        if then == "approval":
            return {"code": "attempt_asked", "label": "Asked a person"}
        return {"code": "not_stopped", "label": "Not stopped"}
    if kind in {"quarantine", "block"}:
        return {"code": "blocked", "label": "Blocked"}
    if kind == "tier3":
        return {"code": "stopped", "label": "Conversation stopped"}
    if kind == "approval":
        if _text(event.get("phase")) == "request":
            return {"code": "asked", "label": "Asked a person"}
        choice = _text(event.get("choice")).lower()
        if choice in _DECLINED:
            return {"code": "declined", "label": "Person said no"}
        if choice in _APPROVED:
            return {"code": "approved", "label": "Person said yes"}
        return {"code": "answered", "label": "Answered"}
    if kind == "bypassed_disarmed":
        return {"code": "allowed", "label": "Let through (paused)"}
    if kind == "ingest_flagged":
        return {"code": "flagged", "label": "Flagged to the agent"}
    if kind == "ingest_unscanned":
        return {"code": "unchecked", "label": "Not checked"}
    if kind in {"init_failed", "cold_start_degraded"}:
        return {"code": "degraded", "label": "Basic checks only"}
    return {"code": "recorded", "label": "Recorded"}


def describe_event(
    event: Mapping[str, object],
    follower: Mapping[str, object] | None = None,
) -> str:
    """One sentence for what an enforcement event did. ``follower`` is as for :func:`outcome`."""
    kind = _text(event.get("event_type"))
    tool = _text(event.get("tool"))
    rule = _text(event.get("rule_id"))
    family = _FAMILY.get(rule_family(rule), "")
    if rule.endswith("destructive-recursive"):
        return "Blocked a shell command that would delete files recursively."
    if kind == "block" and _text(event.get("tier")) == "tier2":
        subject = f"a {tool} call" if tool else "a tool call"
        return f"Blocked {subject} because this conversation's risk score is too high."
    if kind in {"quarantine", "block"}:
        if tool in {"terminal", "execute_code"}:
            subject = "a shell command"
        elif tool:
            subject = f"a {tool} call"
        else:
            subject = "a tool call"
        if family:
            return f"Blocked {subject} that contained {family}."
        return f"Blocked {subject}."
    if kind == "tier3":
        return "Stopped every tool call because the session reached the highest risk level."
    if kind == "bypassed_disarmed":
        return "Let a tool call through because protection is paused, and recorded it."
    if kind == "init_failed":
        return "Used only the basic checks, because the scanners did not finish starting."
    if kind == "cold_start_degraded":
        return "Used only the basic checks, because the scanners were still starting."
    if kind == "selfmod_attempt":
        subject = f"A {tool} call" if tool else "A tool call"
        verdict = outcome(event, follower)["code"]
        if verdict == "attempt_blocked":
            why = _stop_reason(follower)
            return f"{subject} tried to change Petasos or Hermes settings. It was blocked, {why}."
        if verdict == "attempt_asked":
            return (
                f"{subject} tried to change Petasos or Hermes settings. "
                "It waited for a person to approve it."
            )
        return (
            f"{subject} tried to change Petasos or Hermes settings. Petasos recorded it "
            "and did not stop it, so the change may have gone through."
        )
    if kind == "ingest_flagged":
        source = f"a {tool} result" if tool else "a tool result"
        found = family or "something that matched a rule"
        return f"Warned the agent that {source} contained {found}, and passed it on marked."
    if kind == "ingest_unscanned":
        return "Could not scan a tool result, and passed it on unmarked."
    if kind == "approval":
        subject = f"a {tool} call" if tool else "a tool call"
        phase = _text(event.get("phase"))
        if phase == "request":
            return f"Asked a person before running {subject}."
        verdict = outcome(event)["code"]
        if verdict == "declined":
            return f"A person said no to {subject} that Petasos asked about."
        if verdict == "approved":
            return f"A person allowed {subject} that Petasos asked about."
        return "Recorded the answer to an approval ask."
    if tool:
        return f"Recorded a Petasos event for {tool}."
    return "Recorded a Petasos event."


def _stop_reason(follower: Mapping[str, object] | None) -> str:
    then = _text(follower.get("event_type")) if follower is not None else ""
    if then == "tier3":
        return "because the conversation had already been stopped"
    if then == "block":
        return "because the conversation's risk score was already too high"
    return "because the call also matched another rule"


def selfmod_note(event: Mapping[str, object], follower: Mapping[str, object] | None) -> str:
    """What an attempt to change the guardrails means for the person reading it."""
    if outcome(event, follower)["code"] == "not_stopped":
        return (
            "Recording an attempt does not stop it. Petasos blocks such a call only when "
            "the conversation is already blocked or the call matches another rule. Check "
            "the target below for a change you did not make."
        )
    return (
        "The attempt did not go through. Recording it does not stop a call on its own: "
        "this one was stopped for the reason above."
    )


def selfmod_target(event: Mapping[str, object]) -> str:
    """The file or setting an attempt aimed at, from the recorded reason, or empty."""
    reason = _text(event.get("reason"))
    marker = "selfmod target:"
    if reason.startswith(marker):
        return reason[len(marker) :].strip()
    return ""


# Who can change Petasos's settings, served with the status.
WHO_CAN_CHANGE = MappingProxyType(
    {
        "agent": (
            "If the agent tries to change Petasos's or Hermes's settings, Petasos records "
            "the attempt and raises the conversation's risk score. Recording does not stop "
            "it: the call is blocked only once the conversation is blocked, or when it "
            "matches another rule."
        ),
        "you": (
            "Here, in Hermes Desktop's plugin settings, or with hermes config on the command line."
        ),
        "switches": (
            "Hermes's plugin switch, on the Plugins page, decides whether Petasos runs at "
            "all. Pause, here, keeps Petasos running and recording."
        ),
    }
)

# Sentences about the record itself, served with each event.
MATCHED_TEXT_NOTE = (
    "Petasos does not keep the matched text in its record, because it can contain "
    "secrets. Try it shows exactly what a rule matches."
)

SIGNATURE_MEANING = MappingProxyType(
    {
        "verified": (
            "Signed with this profile's session secret, and the signature matches: this "
            "entry has not been changed since Petasos wrote it. A signature cannot show "
            "whether other entries were deleted."
        ),
        "failed": (
            "The signature does not match. This entry was changed after Petasos wrote it, "
            "or was written by something else. Do not trust it."
        ),
        "off": (
            "Not signed, because this profile has no session secret. Anything that can "
            "write to the profile could change this entry without it showing here."
        ),
    }
)


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
