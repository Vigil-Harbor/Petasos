"""Read the enforcement spool for one home.

The reader never writes. A large file is read from the end, a partial last
line is left unread, and a bad line is skipped. Rotation, truncation, and a
file that is still being appended do not raise.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from petasos.enforce.approvals import redact_display_text
from petasos.enforce.events import classify_integrity_failure, verify_event
from petasos.hermes.dashboard.errors import ApiError, envelope
from petasos.hermes.dashboard.words import (
    MATCHED_TEXT_NOTE,
    SIGNATURE_MEANING,
    describe_event,
    kind_label,
    outcome,
    rule_sentence,
    selfmod_note,
    selfmod_target,
)

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_PAGE_BYTES = 1_000_000
MAX_SUMMARY_BYTES = 4_000_000
_DISPLAY_LIMIT = 500
_MAX_TEXT = 200
# Events Petasos writes for one tool call land within this many seconds.
_SAME_CALL_S = 5.0

_KEEP = frozenset(
    {
        "armed",
        "choice",
        "credential_redaction",
        "decided_by",
        "direction",
        "event_type",
        "item_id",
        "param_scan_degraded",
        "phase",
        "rule_id",
        "scan_id",
        "session_id",
        "session_key",
        "severity",
        "sig",
        "surface",
        "tier",
        "timestamp",
        "tool",
        "tool_call_id",
        "turn_id",
    }
)

_Redactor = Callable[..., str]


@dataclass(frozen=True, slots=True)
class ActivityQuery:
    """Filters for one read. Times are unix seconds. Empty strings are ignored.

    ``text`` matches an event id exactly or by its start, or any of the event's
    words (its sentence, tool, conversation, rule, kind and reason), ignoring case.
    """

    since: float | None = None
    until: float | None = None
    kind: str | None = None
    tool: str | None = None
    session: str | None = None
    severity: str | None = None
    text: str | None = None
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True, slots=True)
class _Located:
    record: dict[str, Any]
    source: str
    offset: int
    corrupt: bool


def read_page(
    spool: Path,
    rotated: Path,
    *,
    key: bytes | None,
    verification: str,
    query: ActivityQuery,
    cursor: str | None = None,
    redactor: _Redactor | None = None,
    max_bytes: int = MAX_PAGE_BYTES,
) -> dict[str, Any]:
    """One page of events, newest first.

    ``cursor`` is opaque. A cursor that points past a file that has shrunk
    starts again at the newest event and sets ``cursor_reset``.
    """
    limit = query.limit
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError("invalid_query", f"Ask for between 1 and {MAX_LIMIT} events.")
    parsed = _decode_cursor(cursor) if cursor else None
    if cursor and parsed is None:
        raise ApiError("invalid_cursor", "That page marker is not valid. Refresh the list.")
    reset = _cursor_reset(spool, rotated, parsed)
    located, complete = _collect(spool, rotated, max_bytes, None if reset else parsed)
    followers = _followers(located)
    matched = [
        item
        for item in located
        if not item.corrupt and _matches(item.record, query, followers.get(id(item)))
    ]
    skipped = sum(1 for item in located if item.corrupt)
    page = matched[:limit]
    more = len(matched) > limit or not complete
    next_cursor = None
    if more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last.source, last.offset)
    events = [_event(item.record, key, redactor, followers.get(id(item))) for item in page]
    return envelope(
        events=events,
        next_cursor=next_cursor,
        cursor_reset=reset,
        complete=complete and not more,
        skipped_lines=skipped,
        integrity=_integrity(events, key, verification),
    )


def read_event(
    spool: Path,
    rotated: Path,
    scan_id: str,
    *,
    key: bytes | None,
    verification: str,
    redactor: _Redactor | None = None,
    max_bytes: int = MAX_SUMMARY_BYTES,
) -> dict[str, Any]:
    """One event by ``scan_id``, or an error when it is not in the scanned range."""
    if not scan_id or "/" in scan_id or len(scan_id) > 80:
        raise ApiError("not_found", "That event was not found.", status=404)
    located, complete = _collect(spool, rotated, max_bytes, None)
    followers = _followers(located)
    for item in located:
        if item.corrupt:
            continue
        if item.record.get("scan_id") == scan_id:
            event = _event(item.record, key, redactor, followers.get(id(item)))
            return envelope(
                event=event,
                complete=complete,
                integrity=_integrity([event], key, verification),
            )
    if not complete:
        raise ApiError(
            "not_found",
            "That event was not found in the recent record. "
            "The older part of the spool was not read.",
            status=404,
        )
    raise ApiError("not_found", "That event was not found.", status=404)


def summarize(
    spool: Path,
    rotated: Path,
    *,
    key: bytes | None,
    verification: str,
    query: ActivityQuery,
    max_bytes: int = MAX_SUMMARY_BYTES,
) -> dict[str, Any]:
    """Counts over the events that match ``query``.

    A spool larger than ``max_bytes`` sets ``complete`` false. The counts then
    cover the newest bytes only.
    """
    located, complete = _collect(spool, rotated, max_bytes, None)
    followers = _followers(located)
    counts: dict[str, int] = {}
    severities: dict[str, int] = {}
    tools: dict[str, int] = {}
    sessions: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    blocked = 0
    failed = 0
    checked = 0
    shown = 0
    for item in located:
        if item.corrupt:
            continue
        follower = followers.get(id(item))
        if not _matches(item.record, query, follower):
            continue
        shown += 1
        kind = item.record.get("event_type")
        if isinstance(kind, str) and kind:
            counts[kind] = counts.get(kind, 0) + 1
        severity = item.record.get("severity")
        if isinstance(severity, str) and severity:
            folded = severity.lower()
            severities[folded] = severities.get(folded, 0) + 1
        _count(tools, item.record.get("tool"))
        _count(sessions, item.record.get("session_id"))
        _count(outcomes, outcome(item.record, follower)["code"])
        if kind in {"quarantine", "block", "tier3"}:
            blocked += 1
        if key is not None:
            checked += 1
            if not verify_event(item.record, key):
                failed += 1
    return envelope(
        total=shown,
        blocked=blocked,
        by_kind=counts,
        by_severity=severities,
        by_tool=tools,
        by_session=sessions,
        by_outcome=outcomes,
        kind_labels={kind: kind_label(kind) for kind in counts},
        complete=complete,
        integrity={
            "mode": _mode(key, checked, failed),
            "reason": verification if key is None else "",
            "checked": checked,
            "failed": failed,
        },
    )


def _count(counts: dict[str, int], value: object) -> None:
    if isinstance(value, str) and value:
        counts[value] = counts.get(value, 0) + 1


def _collect(
    spool: Path,
    rotated: Path,
    max_bytes: int,
    cursor: tuple[str, int] | None,
) -> tuple[list[_Located], bool]:
    """Newest records first, reading at most ``max_bytes`` from the end or the cursor."""
    if cursor is None or cursor[0] == "live":
        end = None if cursor is None else cursor[1]
        live_rows, live_done, used = _window(spool, "live", end, max_bytes)
        if not live_done:
            return live_rows, False
        rot_budget = max_bytes - used
        if rot_budget <= 0:
            return live_rows, _size(rotated) == 0
        rot_rows, rot_done, _used = _window(rotated, "rot", None, rot_budget)
        return live_rows + rot_rows, rot_done
    rot_rows, rot_done, _used = _window(rotated, "rot", cursor[1], max_bytes)
    return rot_rows, rot_done


def _window(
    path: Path,
    source: str,
    end: int | None,
    budget: int,
) -> tuple[list[_Located], bool, int]:
    """Records with offset below ``end``, newest first.

    The second value is True when the read reached the start of the file.
    The third is how many bytes were read. A trailing partial line is not a
    record: a writer may still be appending it.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return [], True, 0
    stop = size if end is None else min(end, size)
    if stop <= 0 or budget <= 0:
        return [], True, 0
    take = min(stop, budget)
    start = stop - take
    try:
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read(take)
    except OSError:
        return [], True, 0
    if start > 0:
        newline = data.find(b"\n")
        if newline < 0:
            return [], False, len(data)
        start += newline + 1
        data = data[newline + 1 :]
    if data.endswith(b"\n"):
        body = data[:-1]
        closed = True
    else:
        cut = data.rfind(b"\n")
        if cut < 0:
            return [], start == 0, len(data)
        body = data[:cut]
        closed = False
    rows: list[_Located] = []
    offset = start
    for raw in body.split(b"\n"):
        line_at = offset
        offset += len(raw) + 1
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            rows.append(_Located({}, source, line_at, True))
            continue
        if not isinstance(parsed, dict):
            rows.append(_Located({}, source, line_at, True))
            continue
        rows.append(_Located(parsed, source, line_at, False))
    rows.reverse()
    return rows, start == 0 and closed, take


def _followers(located: list[_Located]) -> dict[int, dict[str, Any]]:
    """For each attempt to change the guardrails, the event written right after it.

    ``located`` is newest first, so the event written next is the one before
    it in the list. It counts only when it is for the same conversation and
    tool and was written within a few seconds: that is the same tool call.
    """
    found: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(located):
        if item.corrupt or item.record.get("event_type") != "selfmod_attempt" or index == 0:
            continue
        newer = located[index - 1]
        if newer.corrupt or newer.source != item.source:
            continue
        record = item.record
        other = newer.record
        if other.get("session_id") != record.get("session_id"):
            continue
        if other.get("tool") != record.get("tool"):
            continue
        first = record.get("timestamp")
        second = other.get("timestamp")
        if not isinstance(first, (int, float)) or not isinstance(second, (int, float)):
            continue
        if abs(second - first) > _SAME_CALL_S:
            continue
        found[id(item)] = other
    return found


def _matches(
    record: Mapping[str, Any],
    query: ActivityQuery,
    follower: Mapping[str, Any] | None = None,
) -> bool:
    stamp = record.get("timestamp")
    if query.since is not None and (not isinstance(stamp, (int, float)) or stamp < query.since):
        return False
    if query.until is not None and (not isinstance(stamp, (int, float)) or stamp > query.until):
        return False
    if query.kind and record.get("event_type") != query.kind:
        return False
    if query.tool and record.get("tool") != query.tool:
        return False
    if query.session and record.get("session_id") != query.session:
        return False
    if query.severity:
        severity = record.get("severity")
        if not isinstance(severity, str) or severity.lower() != query.severity.lower():
            return False
    if query.text:
        return _text_matches(record, query.text, follower)
    return True


def _text_matches(
    record: Mapping[str, Any],
    text: str,
    follower: Mapping[str, Any] | None,
) -> bool:
    needle = text.strip().casefold()[:_MAX_TEXT]
    if not needle:
        return True
    scan_id = record.get("scan_id")
    if isinstance(scan_id, str) and scan_id.casefold().startswith(needle):
        return True
    kind = record.get("event_type")
    words = [
        describe_event(record, follower),
        kind_label(kind) if isinstance(kind, str) else "",
    ]
    for name in ("tool", "session_id", "rule_id", "reason", "event_type", "severity"):
        value = record.get(name)
        if isinstance(value, str):
            words.append(value)
    return any(needle in word.casefold() for word in words)


def _event(
    record: Mapping[str, Any],
    key: bytes | None,
    redactor: _Redactor | None,
    follower: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    shown = _redact_record(record, redactor)
    shown["summary"] = describe_event(record, follower)
    shown["outcome"] = outcome(record, follower)
    kind = record.get("event_type")
    shown["kind_label"] = kind_label(kind) if isinstance(kind, str) else ""
    rule = record.get("rule_id")
    shown["rule_sentence"] = rule_sentence(rule) if isinstance(rule, str) else ""
    shown["matched_note"] = MATCHED_TEXT_NOTE if isinstance(rule, str) and rule else ""
    if kind == "selfmod_attempt":
        target = selfmod_target(record)
        shown["target"] = _redact(target, redactor) if target else ""
        shown["outcome_note"] = selfmod_note(record, follower)
    shown["integrity"] = _one(record, key)
    return shown


def _redact_record(record: Mapping[str, Any], redactor: _Redactor | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        name = str(key)
        if name in _KEEP:
            result[name] = value
            continue
        result[name] = _redact(value, redactor)
    return result


def _redact(value: object, redactor: _Redactor | None) -> object:
    if isinstance(value, str):
        shown, _status = redact_display_text(value, _DISPLAY_LIMIT, redact=redactor)
        return shown
    if isinstance(value, list):
        return [_redact(item, redactor) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _redact(item, redactor) for key, item in value.items()}
    return value


def _one(record: Mapping[str, Any], key: bytes | None) -> dict[str, str]:
    if key is None:
        return {"status": "off", "meaning": SIGNATURE_MEANING["off"]}
    if verify_event(record, key):
        return {"status": "verified", "meaning": SIGNATURE_MEANING["verified"]}
    failure = classify_integrity_failure(record)
    if failure == "sig-missing":
        sentence = "This event has no signature."
    else:
        sentence = "This event's signature does not match."
    return {"status": "failed", "reason": sentence, "meaning": SIGNATURE_MEANING["failed"]}


def _integrity(
    events: list[dict[str, Any]],
    key: bytes | None,
    verification: str,
) -> dict[str, Any]:
    failed = sum(1 for event in events if event.get("integrity", {}).get("status") == "failed")
    checked = len(events) if key is not None else 0
    return {
        "mode": _mode(key, checked, failed),
        "reason": verification if key is None else "",
        "checked": checked,
        "failed": failed,
    }


def _mode(key: bytes | None, checked: int, failed: int) -> str:
    if key is None:
        return "off"
    if failed and failed == checked:
        return "failed"
    if failed:
        return "mixed"
    return "verified"


def _encode_cursor(source: str, offset: int) -> str:
    raw = json.dumps({"source": source, "before": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(token: str) -> tuple[str, int] | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        parsed = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    source = parsed.get("source")
    before = parsed.get("before")
    if source not in {"live", "rot"} or type(before) is not int or before < 0:
        return None
    return source, before


def _cursor_reset(
    spool: Path,
    rotated: Path,
    cursor: tuple[str, int] | None,
) -> bool:
    if cursor is None:
        return False
    return cursor[1] > _size(spool if cursor[0] == "live" else rotated)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
