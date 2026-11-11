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
        return {"code": "allowed", "label": "Let through"}
    if kind == "ingest_flagged":
        return {"code": "flagged", "label": "Flagged to the agent"}
    if kind == "ingest_unscanned":
        return {"code": "unchecked", "label": "Not checked"}
    if kind in {"init_failed", "cold_start_degraded"}:
        return {"code": "degraded", "label": "Basic checks only"}
    return {"code": "recorded", "label": "Recorded"}


# What the agent was doing, for Hermes tools whose kind of action Petasos
# knows: "tried to <action>". A tool not listed here is named by its id.
_ACTIONS = MappingProxyType(
    {
        "terminal": "run a shell command",
        "execute_code": "run code",
        "write_file": "write a file",
        "patch": "edit a file",
        "read_file": "read a file",
        "search_files": "search files",
        "send_message": "send a message",
        "web_search": "search the web",
        "web_extract": "read a web page",
        "browser_navigate": "open a web page",
        "delegate_task": "start a helper agent",
        "memory": "change its memory",
        "skill_manage": "change a skill",
        "cronjob": "schedule a job",
    }
)

# The thing a tool hands back, for a sentence about a tool result.
_RESULTS = MappingProxyType(
    {
        "web_extract": "a web page it read",
        "web_search": "search results it read",
        "browser_navigate": "a web page it opened",
        "read_file": "a file it read",
        "search_files": "files it searched",
        "terminal": "a command's output",
        "execute_code": "code output",
    }
)


def action(tool: str) -> str:
    """What the agent tried to do with ``tool``, or empty when Petasos does not know."""
    return _ACTIONS.get(tool, "")


def _attempt(tool: str) -> str:
    """An attempt, named by its action when known, else by the tool's id."""
    known = _ACTIONS.get(tool)
    if known:
        return f"an attempt to {known}"
    if tool:
        return f"a {tool} call"
    return "an action"


def describe_event(
    event: Mapping[str, object],
    follower: Mapping[str, object] | None = None,
) -> str:
    """One sentence for what an enforcement event did. ``follower`` is as for :func:`outcome`.

    The sentence says what the agent tried to do where Petasos knows the kind
    of action; the tool's id is served beside it, not in it.
    """
    kind = _text(event.get("event_type"))
    tool = _text(event.get("tool"))
    rule = _text(event.get("rule_id"))
    family = _FAMILY.get(rule_family(rule), "")
    subject = _attempt(tool)
    if rule.endswith("destructive-recursive"):
        return "Blocked a shell command that would delete files recursively."
    if kind == "block" and _text(event.get("tier")) == "tier2":
        return f"Blocked {subject}: warning signs in this conversation had added up."
    if kind in {"quarantine", "block"}:
        if family:
            return f"Blocked {subject} that contained {family}."
        return f"Blocked {subject}."
    if kind == "tier3":
        return "Stopped the conversation at the highest risk level. Every action in it is blocked."
    if kind == "bypassed_disarmed":
        if tool in _ACTIONS:
            return f"Let the agent {_ACTIONS[tool]} unchecked, because protection was paused."
        return f"Let {subject} through unchecked, because protection was paused."
    if kind == "init_failed":
        return "Used only the basic checks: the extra checks did not finish starting."
    if kind == "cold_start_degraded":
        return "Used only the basic checks: the extra checks were still starting."
    if kind == "selfmod_attempt":
        verdict = outcome(event, follower)["code"]
        if verdict == "attempt_blocked":
            why = _stop_reason(follower)
            return f"Blocked an attempt to change Petasos or Hermes settings, {why}."
        if verdict == "attempt_asked":
            return "Asked a person about an attempt to change Petasos or Hermes settings."
        return (
            "Did not stop an attempt to change Petasos or Hermes settings. "
            "The change may have gone through."
        )
    if kind == "ingest_flagged":
        source = _RESULTS.get(tool) or (f"a {tool} result" if tool else "a tool result")
        found = family or "something that matched a rule"
        return f"Warned the agent that {source} contained {found}."
    if kind == "ingest_unscanned":
        return "Could not check a tool result, and passed it on unmarked."
    if kind == "approval":
        phase = _text(event.get("phase"))
        doing = _ACTIONS.get(tool)
        if phase == "request":
            if doing:
                return f"Asked a person before letting the agent {doing}."
            return f"Asked a person before running {subject}."
        verdict = outcome(event)["code"]
        if verdict == "declined":
            if doing:
                return f"A person did not let the agent {doing}."
            return f"A person said no to {subject}."
        if verdict == "approved":
            if doing:
                return f"A person let the agent {doing}."
            return f"A person allowed {subject}."
        return "Recorded the answer to an approval request."
    if tool:
        return f"Recorded a Petasos event for {tool}."
    return "Recorded a Petasos event."


def _stop_reason(follower: Mapping[str, object] | None) -> str:
    then = _text(follower.get("event_type")) if follower is not None else ""
    if then == "tier3":
        return "because the conversation had already been stopped"
    if then == "block":
        return "because warning signs in this conversation had added up"
    return "because it also matched another rule"


def selfmod_note(event: Mapping[str, object], follower: Mapping[str, object] | None) -> str:
    """What an attempt to change the guardrails means for the person reading it."""
    if outcome(event, follower)["code"] == "not_stopped":
        return "The record cannot show whether the change took effect."
    return "The attempt did not go through."


def selfmod_target(event: Mapping[str, object]) -> str:
    """The file or setting an attempt aimed at, from the recorded reason, or empty."""
    reason = _text(event.get("reason"))
    marker = "selfmod target:"
    if reason.startswith(marker):
        return reason[len(marker) :].strip()
    return ""


# What each optional check adds, by the capability the registry lists for it.
# The status names a missing check by what it would add, and the product second.
CAPABILITY_WORDS = MappingProxyType(
    {
        "injection": "reworded hidden instructions",
        "pii": "personal details",
        "code": "risky code",
    }
)

# What the basic checks look for, in the same register.
BASIC_CHECKS_COVER = "Hidden instructions, dangerous commands and disguised text"

# What the checks list is, without a claim about whether they run now.
CHECKS_NOTE = "Basic checks are built in. Extra checks add a model or a code checker."

# What "on" covers. Hermes loads an enabled plugin into every process that
# runs an agent for the profile (chat, gateway, scheduled jobs, the
# dashboard's chat), except a safe-mode session; Petasos reads its settings
# again on each tool call.
PROTECTION_SCOPE = (
    "Every agent Hermes starts from this profile, except in safe mode. "
    "A saved change applies from the agent's next action."
)

# A check's operating state, as a person reads it: whether it is checking
# the agent's actions now. Distinct from whether it is installed or turned on.
OPERATING_WORDS = MappingProxyType(
    {
        "running": "Running",
        "paused": "Paused",
        "stopped": "Not running",
        "failed": "Failed",
        "not_installed": "Not installed",
        "off": "Off",
    }
)

# Where to run the command that adds a check. The command itself is served beside it.
ADD_CHECK_WHERE = (
    "In a terminal on the computer where Hermes runs, run this command, then restart "
    "Hermes with Restart Gateway in the sidebar."
)

# Who can change Petasos's settings, served with the status.
WHO_CAN_CHANGE = MappingProxyType(
    {
        "agent": (
            "An attempt is recorded and raises the conversation's risk score. Recording "
            "alone does not stop it."
        ),
        "you": "Here, in Hermes Desktop's plugin settings, or with hermes config.",
        "switches": (
            "Hermes's plugin switch, on Plugins, decides whether Petasos runs at all. "
            "Pause, here, keeps it running and recording."
        ),
    }
)

# Sentences about the record itself, served with each event.
MATCHED_TEXT_NOTE = (
    "Not kept, because it can contain secrets. To test this rule, paste the text into Try it."
)

# The one line beside the job and strictness when those choices are not in effect.
CHOICES_WHEN_PAUSED = "These apply when protection resumes."
CHOICES_WHEN_HERMES = "These apply when Hermes runs Petasos."
CHOICES_WHEN_UNUSABLE = "These are not in use until the settings can be used."

# What one Try it check does. It builds a pipeline, decides, and throws that away.
CHECK_NOTE = (
    "This check runs no command, writes no file, sends nothing, and adds no Activity record."
)

# The button on a guardrail finding. It opens the settings that differ from the default.
REVIEW_CURRENT_SETTINGS = "Review current settings"

# The disclosure beside a verified activity list. The body is the verified meaning above.
SIGNATURE_LIMIT_LABEL = "What a signature shows"

# Severity words for an event that stored none. A stored rank uses its own word.
_SEVERITY_WORDS = MappingProxyType(
    {
        "critical": "Critical",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "info": "Info",
    }
)
_RISK_EVENT = frozenset({"block", "tier3"})


def severity_label(event: Mapping[str, object]) -> str:
    """The severity word an activity row shows.

    A stored rank is that rank. A block from the conversation's risk score has
    no rank. An event that names no rule matched none. An event that names a
    rule and stores no rank did not record how serious that rule was.
    """
    raw = _text(event.get("severity")).strip().lower()
    if raw:
        return _SEVERITY_WORDS.get(raw, raw[:1].upper() + raw[1:])
    if _text(event.get("event_type")) in _RISK_EVENT:
        return "Conversation risk"
    if _text(event.get("rule_id")).strip():
        return "Not recorded"
    return "No rule"


def change_applies(restart: bool) -> str:
    """When one changed setting takes effect.

    A restart-bound value is what an agent started from now on uses. An agent
    already running keeps the previous value until that agent restarts. This
    does not say which of those has happened.
    """
    if restart:
        return (
            "An agent started from now on uses this. "
            "An agent already running keeps the previous value until it restarts."
        )
    return "Applies from the agent's next tool call."


def saved_effect(lead: str, names: list[str], *, also_live: bool) -> str:
    """When a save takes effect. ``names`` are the restart-bound settings that changed.

    ``lead`` is ``Saved.`` or ``Reset.`` or empty. ``also_live`` is true when the
    same save also changed a setting an agent picks up on its next tool call.
    """
    if not names:
        body = "Petasos uses it from the agent's next tool call."
    else:
        named = ", ".join(names)
        body = (
            f"An agent started from now on uses the saved value for {named}. "
            "An agent already running keeps the previous value until it restarts."
        )
        if also_live:
            body += " Every other saved change applies from the agent's next tool call."
    prefix = f"{lead} " if lead else ""
    return prefix + body


def choices_note(*, usable: bool, running: bool, paused: bool) -> str | None:
    """The line beside the two choices, or None when those choices are in effect.

    ``usable`` is false when the saved settings cannot be used. ``running`` is
    false when Hermes is not running Petasos. ``paused`` is protection paused.
    """
    if not usable:
        return CHOICES_WHEN_UNUSABLE
    if not running:
        return CHOICES_WHEN_HERMES
    if paused:
        return CHOICES_WHEN_PAUSED
    return None


SIGNATURE_MEANING = MappingProxyType(
    {
        "verified": (
            "The signature matches: this entry has not changed since Petasos wrote it. "
            "A signature cannot show whether other entries were deleted."
        ),
        "failed": (
            "The signature does not match. This entry was changed after Petasos wrote it, "
            "or was written by something else. Do not trust it."
        ),
        "off": (
            "Not signed, because this profile has no session secret. Anything that can "
            "write to the profile could change this entry unnoticed."
        ),
    }
)


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
