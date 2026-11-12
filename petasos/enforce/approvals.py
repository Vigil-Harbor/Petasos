"""Approval asks, the command excerpt shown for one, and approval observations.

The host supplies the redactor. This module does not import a host, and it
does not decide whether the host will auto-approve the ask.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from typing import Any

from petasos.limits import MAX_PARAM_TEXT_LEN
from petasos.normalize import _is_strippable

CREDENTIAL_MASKED_NOTICE = "Sensitive content masked locally; exposure unconfirmed."
CREDENTIAL_WITHHELD_NOTICE = "Sensitive display withheld; redaction unavailable."

EXCERPT_BUDGET = 160
_BARE_KEY = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
_EXCERPT_MAX_DEPTH = 16
_EXCERPT_MAX_NODES = 4096

APPROVAL_FIELD_MAX = 200
APPROVAL_DESCRIPTION_MAX = 400
_APPROVAL_TOOL_RE = re.compile(r"^<([^>\n]+)> \(plugin approval rule\)$")

DEGRADED_PATTERN_KEY = "plugin_rule:petasos.degraded"
DEGRADED_CONFIRMED_CHOICES = frozenset({"session", "always"})

_Redact = Callable[..., str]
_LoadRedactor = Callable[[], _Redact]


def redact_display_text(
    value: object,
    limit: int,
    *,
    redact: _Redact | None,
    max_len: int = MAX_PARAM_TEXT_LEN,
) -> tuple[str, str]:
    """Redact one display string, then clip it.

    An empty or non-string value is unchanged. Any failure, including a missing
    redactor, returns a withheld marker and the status ``withheld``. The
    exception is not logged: it can echo the value being protected.
    """
    if not isinstance(value, str) or not value:
        return "", "unchanged"
    try:
        if len(value) > max_len:
            raise ValueError("display input exceeds redaction budget")
        if redact is None:
            raise RuntimeError("redactor unavailable")
        safe = redact(value, force=True, redact_url_credentials=True)
        if not isinstance(safe, str) or len(safe) > max_len:
            raise ValueError("invalid display redaction result")
        status = "unchanged" if safe == value else "redacted"
        return safe[:limit], status
    except Exception:
        return "withheld (redaction unavailable)"[:limit], "withheld"


def credential_reason(reason: str, status: str) -> str:
    """Prefix an operator reason when display redaction changed the text."""
    if status == "redacted":
        return f"{CREDENTIAL_MASKED_NOTICE} {reason}"
    if status == "withheld":
        return f"{CREDENTIAL_WITHHELD_NOTICE} {reason}"
    return reason


def _excerpt_redact_arguments(
    args: Mapping[object, object], redact: Callable[..., str]
) -> list[tuple[str, str]]:
    """Redact original string leaves before JSON escaping or display normalization.

    The host's exact vault-value registry needs the original characters. Work on
    copies only, and withhold the entire excerpt if the input cannot be bounded.
    """
    nodes = 0
    characters = 0
    redaction_characters = 0

    def spend(text: str) -> None:
        nonlocal characters
        characters += len(text)
        if characters > MAX_PARAM_TEXT_LEN:
            raise ValueError("excerpt input exceeds character budget")

    def mask(text: str) -> str:
        nonlocal redaction_characters
        # Count work, not just input: list leaves reuse their parent's field
        # name, and the host may expand a value into a longer masking marker.
        redaction_characters += len(text)
        if redaction_characters > MAX_PARAM_TEXT_LEN:
            raise ValueError("excerpt redaction exceeds character budget")
        masked = redact(text, force=True, redact_url_credentials=True)
        if not isinstance(masked, str) or len(masked) > MAX_PARAM_TEXT_LEN:
            raise ValueError("invalid excerpt redaction result")
        return masked

    def clean(value: object, depth: int, key: str | None = None) -> Any:
        nonlocal nodes
        nodes += 1
        if depth > _EXCERPT_MAX_DEPTH or nodes > _EXCERPT_MAX_NODES:
            raise ValueError("excerpt input exceeds traversal budget")
        if isinstance(value, str):
            spend(value)
            masked = mask(value)
            if key is not None:
                # Retain assignment context for opaque values under secret field
                # names. If redaction changes the key too, withhold rather than
                # trying to recover a value from an ambiguous assignment.
                prefix = key + "="
                assignment = mask(prefix + masked)
                if not assignment.startswith(prefix):
                    raise ValueError("excerpt field name was redacted")
                masked = assignment[len(prefix) :]
            return masked
        if value is None or isinstance(value, (bool, int, float)):
            spend(str(value))
            return value
        if isinstance(value, (list, tuple)):
            return [clean(item, depth + 1, key) for item in value]
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for field, item in value.items():
                if not isinstance(field, str):
                    raise TypeError("non-string excerpt field")
                spend(field)
                safe_field = mask(field)
                if safe_field in result:
                    raise ValueError("excerpt fields collide after redaction")
                result[safe_field] = clean(item, depth + 1, field)
            return result
        raise TypeError("unsupported excerpt argument")

    cleaned = clean(args, 0)
    pairs: list[tuple[str, str]] = []
    serialized_size = 0
    for key, value in cleaned.items():
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        serialized_size += len(key) + 1 + len(text)
        if serialized_size > MAX_PARAM_TEXT_LEN:
            raise ValueError("serialized excerpt exceeds character budget")
        pairs.append((key, text))
    return pairs


def _excerpt_drop_invisible(text: str) -> tuple[str, bool]:
    """Drop invisible non-whitespace characters from approval excerpts."""
    dropped = False
    kept: list[str] = []
    for ch in text:
        if ch.isspace():
            kept.append(ch)
            continue
        if (not ch.isprintable()) or _is_strippable(ch):
            dropped = True
            continue
        kept.append(ch)
    return "".join(kept), dropped


def _excerpt_escape_units(text: str) -> list[str]:
    """One display unit per source character. An escape is never split later."""
    units: list[str] = []
    for ch in text:
        if ch == '"':
            units.append('\\"')
        elif ch == "\\":
            units.append("\\\\")
        elif ch == "\n":
            units.append("\\n")
        elif ch == "\r":
            units.append("\\r")
        elif ch == "\t":
            units.append("\\t")
        elif unicodedata.category(ch) in {"Cc", "Zl", "Zp"} or (ch.isspace() and ch != " "):
            units.append(f"\\u{ord(ch):04x}")
        else:
            units.append(ch)
    return units


def _excerpt_part_full(kind: str, content: list[str]) -> str:
    body = "".join(content)
    if kind == "bare":
        return body
    if kind == "quoted":
        return f'"{body}"'
    return f'="{body}"'


def _excerpt_part_cut(kind: str, content: list[str], remaining: int) -> tuple[str, int]:
    """Fit a part into *remaining* display characters. Close an open quote."""
    if kind == "bare":
        taken: list[str] = []
        used = 0
        for unit in content:
            if used + len(unit) > remaining:
                break
            taken.append(unit)
            used += len(unit)
        return "".join(taken), len(taken)
    reserve = 2 if kind == "quoted" else 3
    if remaining < reserve:
        return "", 0
    room = remaining - reserve
    taken = []
    used = 0
    for unit in content:
        if used + len(unit) > room:
            break
        taken.append(unit)
        used += len(unit)
    body = "".join(taken)
    if kind == "quoted":
        return f'"{body}"', len(taken)
    return f'="{body}"', 1 + len(taken)


def _excerpt_assemble(
    segments: list[list[tuple[str, list[str]]]],
    source_lens: list[int],
    past_raw: int,
) -> tuple[str, int]:
    """Keep whole segments, then cut the first part that does not fit."""
    shown: list[str] = []
    used = 0
    omitted = past_raw
    for index, parts in enumerate(segments):
        sep = 0 if index == 0 else 1
        full = ("" if index == 0 else " ") + "".join(
            _excerpt_part_full(kind, content) for kind, content in parts
        )
        if used + len(full) <= EXCERPT_BUDGET:
            shown.append(full)
            used += len(full)
            continue
        if used + sep > EXCERPT_BUDGET:
            omitted += sum(source_lens[index:])
            break
        if sep:
            shown.append(" ")
            used += 1
        represented = 0
        remaining = EXCERPT_BUDGET - used
        cut = False
        for kind, content in parts:
            if cut:
                break
            piece = _excerpt_part_full(kind, content)
            if len(piece) <= remaining:
                shown.append(piece)
                remaining -= len(piece)
                used += len(piece)
                represented += len(content) if kind != "value" else 1 + len(content)
                continue
            cut_text, cut_source = _excerpt_part_cut(kind, content, remaining)
            if cut_text:
                shown.append(cut_text)
            represented += cut_source
            cut = True
        omitted += source_lens[index] - represented
        omitted += sum(source_lens[index + 1 :])
        break
    return "".join(shown), omitted


def command_excerpt(args: object, result: object, *, load_redactor: _LoadRedactor) -> str:
    """Capped, redacted, quoted command excerpt. Fail closed. Never raises.

    ``load_redactor`` is called only after a PII finding and an empty argument
    map have been ruled out. A failure to load it withholds the excerpt.
    """
    try:
        findings = getattr(result, "findings", ())
        for finding in findings:
            if getattr(finding, "finding_type", None) == "pii":
                return "withheld (PII in parameters)"
        if not isinstance(args, Mapping) or not args:
            if not args:
                return "(no parameters)"
            raise TypeError("non-mapping args")
        try:
            redact_sensitive_text = load_redactor()
        except Exception:
            return "withheld (redactor unavailable)"
        changed = False

        def redact(text: str, **options: bool) -> str:
            nonlocal changed
            safe: str = redact_sensitive_text(text, **options)
            if not isinstance(safe, str):
                raise ValueError("invalid excerpt redaction result")
            changed = changed or safe != text
            return safe

        taken = _excerpt_redact_arguments(args, redact)
        if not taken:
            return "(no parameters)"
        segments: list[list[tuple[str, list[str]]]] = []
        source_lens: list[int] = []
        invisible = False
        for key_s, value_s in taken:
            canon_key, dropped_key = _excerpt_drop_invisible(key_s)
            canon_value, dropped_value = _excerpt_drop_invisible(value_s)
            invisible = invisible or dropped_key or dropped_value
            raw_segment = f"{canon_key}={canon_value}"
            try:
                redacted = redact(raw_segment, force=True, redact_url_credentials=True)
            except Exception:
                return "withheld (redactor unavailable)"
            if not isinstance(redacted, str):
                return "withheld (redactor unavailable)"
            if redacted.startswith(canon_key + "="):
                value_text = redacted[len(canon_key) + 1 :]
                key_kind = "bare" if _BARE_KEY.fullmatch(canon_key) else "quoted"
                key_units = (
                    list(canon_key) if key_kind == "bare" else _excerpt_escape_units(canon_key)
                )
                segments.append(
                    [
                        (key_kind, key_units),
                        ("value", _excerpt_escape_units(value_text)),
                    ]
                )
                source_lens.append(len(canon_key) + 1 + len(value_text))
            else:
                segments.append([("quoted", _excerpt_escape_units(redacted))])
                source_lens.append(len(redacted))
        body, omitted = _excerpt_assemble(segments, source_lens, 0)
        suffix = f" (+{omitted} chars not shown)" if omitted else ""
        if changed:
            suffix += f" ({CREDENTIAL_MASKED_NOTICE})"
        if invisible:
            suffix += " (invisible characters removed)"
        return body + suffix
    except Exception:
        return "withheld (excerpt unavailable)"


def approval_text(value: object, *, limit: int = APPROVAL_FIELD_MAX) -> str:
    """Coerce a hook field to str, then cap it. A non-str becomes empty."""
    if not isinstance(value, str):
        return ""
    if len(value) > limit:
        return value[:limit]
    return value


def approval_pattern_keys(value: object) -> list[str]:
    """Keep str elements only, cap each, and stop at 8. A non-list is empty."""
    if not isinstance(value, list):
        return []
    kept: list[str] = []
    for item in value:
        if isinstance(item, str):
            kept.append(approval_text(item))
            if len(kept) == 8:
                break
    return kept


def approval_session_id(session_id: object, session_key: object) -> str:
    """Prefer a non-empty str session_id, else a non-empty str session_key."""
    if isinstance(session_id, str) and session_id:
        chosen: object = session_id
    elif isinstance(session_key, str) and session_key:
        chosen = session_key
    else:
        chosen = ""
    return approval_text(chosen)


def approval_choice(phase: str, raw: object) -> str | None:
    """Request phase is always null. A response stores str(choice), or null."""
    if phase == "request" or raw is None:
        return None
    return approval_text(str(raw))


def approval_decided_by(value: object) -> str | None:
    """A str is capped. Anything else is null (not an empty string)."""
    if not isinstance(value, str):
        return None
    return approval_text(value)


def approval_tool(command: str) -> str:
    """Bracketed plugin-rule display target, else empty (shell and other prompts)."""
    match = _APPROVAL_TOOL_RE.match(command)
    if match is None:
        return ""
    name = match.group(1)
    return name if isinstance(name, str) else ""


def redaction_status(statuses: set[str]) -> str:
    """One status for several fields. Withheld wins over redacted."""
    if "withheld" in statuses:
        return "withheld"
    if "redacted" in statuses:
        return "redacted"
    return "unchanged"


def approval_event(
    phase: str,
    *,
    choice: object,
    armed: bool,
    command: str,
    description: str,
    redaction: str,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one approval observation. The caller writes it."""
    session_key = approval_text(fields.get("session_key"))
    surface = approval_text(fields.get("surface"))
    tool_call_id = approval_text(fields.get("tool_call_id"))
    turn_id = approval_text(fields.get("turn_id"))
    pattern_keys = approval_pattern_keys(fields.get("pattern_keys"))
    decided_by = approval_decided_by(fields.get("decided_by"))
    stored_choice = approval_choice(phase, choice)
    rule_id = approval_text(fields.get("pattern_key"))
    tool = approval_tool(approval_text(fields.get("command")))
    session_id = approval_session_id(fields.get("session_id"), fields.get("session_key"))
    coalesced = fields.get("coalesced") is True
    reason = credential_reason(
        "approval requested" if phase == "request" else "approval response", redaction
    )
    return {
        "event_type": "approval",
        "phase": phase,
        "choice": stored_choice,
        "rule_id": rule_id,
        "pattern_keys": pattern_keys,
        "tool": tool,
        "session_id": session_id,
        "session_key": session_key,
        "surface": surface,
        "tool_call_id": tool_call_id,
        "turn_id": turn_id,
        "command": command,
        "description": description,
        "credential_redaction": redaction,
        "decided_by": decided_by,
        "coalesced": coalesced,
        "reason": reason,
        "armed": armed,
        "tier": None,
        "severity": None,
        "param_scan_degraded": False,
        "direction": "tool_call",
        "bypassed_count": None,
    }


def degraded_pending_key(
    hermes_session_id: object, turn_id: object, tool_call_id: object
) -> tuple[str, str, str] | None:
    """Build the pending key.

    All three components must be non-empty strings. An empty, missing, or
    non-str component stores nothing and pops nothing.
    """
    if (
        isinstance(hermes_session_id, str)
        and hermes_session_id != ""
        and isinstance(turn_id, str)
        and turn_id != ""
        and isinstance(tool_call_id, str)
        and tool_call_id != ""
    ):
        return (hermes_session_id, turn_id, tool_call_id)
    return None


def degraded_choice_confirmed(choice: object) -> bool:
    """True when the host confirmed a degraded approve for the session or always."""
    return isinstance(choice, str) and choice in DEGRADED_CONFIRMED_CHOICES


def is_degraded_pattern(pattern_key: object) -> bool:
    """True when the approval pattern is the degraded-scan rule."""
    return pattern_key == DEGRADED_PATTERN_KEY
