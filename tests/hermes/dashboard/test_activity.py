"""The activity reader against spools that are awkward on purpose."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import pytest

from petasos.enforce.events import EventSpool, verification_key
from petasos.hermes.dashboard.activity import ActivityQuery, read_event, read_page, summarize
from petasos.hermes.dashboard.errors import ApiError

_OFF = "No session secret is set, so events are not signed and cannot be checked."


def _identity(value: str, **_kwargs: object) -> str:
    return value


def _rot(live: Path) -> Path:
    return Path(str(live) + ".rot")


def _page(
    live: Path,
    *,
    key: bytes | None = None,
    verification: str = _OFF,
    query: ActivityQuery | None = None,
    cursor: str | None = None,
    redactor: Callable[..., str] = _identity,
    max_bytes: int = 1_000_000,
) -> Any:
    return read_page(
        live,
        _rot(live),
        key=key,
        verification=verification,
        query=ActivityQuery() if query is None else query,
        cursor=cursor,
        redactor=redactor,
        max_bytes=max_bytes,
    )


def _emit(path: Path, events: list[dict[str, Any]], *, secret: bytes | None = None) -> None:
    spool = EventSpool(str(path), secret=secret)
    for event in events:
        assert spool.emit(event)


def test_pages_are_newest_first(tmp_path: Path) -> None:
    """A cursor walks backward and does not repeat an event."""
    live = tmp_path / "petasos-enforcement.jsonl"
    rows = [
        {"event_type": "quarantine", "tool": "terminal", "reason": f"n{i}", "rule_id": "r"}
        for i in range(5)
    ]
    _emit(live, rows)
    limited = ActivityQuery(limit=2)
    first = _page(live, query=limited)
    assert [event["reason"] for event in first["events"]] == ["n4", "n3"]
    second = _page(live, query=limited, cursor=first["next_cursor"])
    assert [event["reason"] for event in second["events"]] == ["n2", "n1"]
    assert first["integrity"]["mode"] == "off"
    assert "session secret" in first["integrity"]["reason"]


def test_a_rotated_spool_is_older_than_the_live_file(tmp_path: Path) -> None:
    """Events in the rotated sibling come after the live file."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(live, [{"event_type": "quarantine", "tool": "terminal", "reason": "old"}])
    rotated = Path(str(live) + ".rot")
    live.rename(rotated)
    _emit(live, [{"event_type": "quarantine", "tool": "terminal", "reason": "new"}])
    body = _page(live)
    assert [event["reason"] for event in body["events"]] == ["new", "old"]


def test_a_truncated_cursor_starts_again(tmp_path: Path) -> None:
    """A cursor past the end of a shrunk file does not raise."""
    live = tmp_path / "petasos-enforcement.jsonl"
    rows = [{"event_type": "block", "tool": "write_file", "reason": str(i)} for i in range(4)]
    _emit(live, rows)
    limited = ActivityQuery(limit=2)
    first = _page(live, query=limited)
    live.write_text("", encoding="utf-8")
    again = _page(live, query=limited, cursor=first["next_cursor"])
    assert again["cursor_reset"] is True
    assert again["events"] == []


def test_corrupt_and_partial_lines_are_skipped(tmp_path: Path) -> None:
    """A bad line is counted, and a line without a newline is not a record yet."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(live, [{"event_type": "quarantine", "tool": "terminal", "reason": "kept"}])
    with live.open("a", encoding="utf-8") as handle:
        handle.write("this is not json\n")
        handle.write('{"event_type": "quarantine", "reason": "partial"}')
    body = _page(live)
    assert [event["reason"] for event in body["events"]] == ["kept"]
    assert body["skipped_lines"] == 1


def test_a_large_spool_is_not_read_whole(tmp_path: Path) -> None:
    """The newest event is returned from a byte cap smaller than the file."""
    live = tmp_path / "petasos-enforcement.jsonl"
    rows = [
        {"event_type": "quarantine", "tool": "terminal", "reason": f"row-{i:04d}"}
        for i in range(40)
    ]
    _emit(live, rows)
    assert live.stat().st_size > 2000
    body = _page(live, query=ActivityQuery(limit=5), max_bytes=600)
    assert body["complete"] is False
    assert body["events"]
    assert body["events"][0]["reason"] == "row-0039"


def test_filters_and_summary(tmp_path: Path) -> None:
    """Kind, tool, and time filters apply to the page and to the counts."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {"event_type": "quarantine", "tool": "terminal", "severity": "high", "timestamp": 10},
            {"event_type": "bypassed_disarmed", "tool": "read_file", "timestamp": 20},
            {"event_type": "quarantine", "tool": "terminal", "severity": "high", "timestamp": 30},
        ],
    )
    query = ActivityQuery(kind="quarantine", tool="terminal", since=15, until=40)
    page = _page(live, query=query)
    assert len(page["events"]) == 1
    assert page["events"][0]["timestamp"] == 30
    summary = summarize(live, Path(str(live) + ".rot"), key=None, verification=_OFF, query=query)
    assert summary["total"] == 1
    assert summary["blocked"] == 1
    assert summary["by_kind"] == {"quarantine": 1}


def test_a_signed_event_verifies_and_a_tampered_one_does_not(tmp_path: Path) -> None:
    """The reader checks the spool signature and does not need the process-wide key."""
    live = tmp_path / "petasos-enforcement.jsonl"
    secret = b"sandbox-session-secret"
    _emit(
        live,
        [{"event_type": "quarantine", "tool": "terminal", "reason": "signed"}],
        secret=secret,
    )
    key = verification_key(secret)
    assert key is not None
    good = _page(live, key=key, verification="")
    assert good["events"][0]["integrity"]["status"] == "verified"
    assert good["integrity"]["mode"] == "verified"
    assert good["integrity"]["label"] == "1 signature verified"
    assert "cannot show whether other entries were deleted" in good["integrity"]["limit"]
    assert good["integrity"]["limit_label"]
    raw = live.read_text(encoding="utf-8")
    live.write_text(raw.replace("signed", "edited"), encoding="utf-8")
    bad = _page(live, key=key, verification="")
    assert bad["events"][0]["integrity"]["status"] == "failed"
    assert bad["integrity"]["mode"] == "failed"


def test_one_event_and_a_missing_one(tmp_path: Path) -> None:
    """A scan id returns that record. An unknown id is an error."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(live, [{"event_type": "tier3", "tool": "terminal", "scan_id": "e-known"}])
    found = read_event(
        live,
        Path(str(live) + ".rot"),
        "e-known",
        key=None,
        verification=_OFF,
        redactor=_identity,
    )
    assert found["event"]["scan_id"] == "e-known"
    assert "highest risk" in found["event"]["summary"]
    with pytest.raises(ApiError) as caught:
        read_event(
            live,
            _rot(live),
            "e-missing",
            key=None,
            verification=_OFF,
            redactor=_identity,
        )
    assert caught.value.status == 404


def test_a_destructive_command_is_described_in_plain_words(tmp_path: Path) -> None:
    """The summary sentence names a recursive delete without requiring the front end to."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {
                "event_type": "quarantine",
                "tool": "terminal",
                "rule_id": "petasos.syntactic.command.destructive-recursive",
                "reason": "rm -rf /var",
            }
        ],
    )
    body = _page(live)
    summary = "Blocked a shell command that would delete files recursively."
    assert body["events"][0]["summary"] == summary


def test_redaction_hides_a_secret_in_the_reason(tmp_path: Path) -> None:
    """Content fields go through the redactor. The scan id does not."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {
                "event_type": "quarantine",
                "tool": "terminal",
                "reason": "token sk-secret",
                "scan_id": "e-1",
            }
        ],
    )

    def _mask(value: str, **_kwargs: object) -> str:
        return value.replace("sk-secret", "[hidden]")

    body = _page(live, redactor=_mask)
    assert body["events"][0]["reason"] == "token [hidden]"
    assert body["events"][0]["scan_id"] == "e-1"
    dumped = json.dumps(body)
    assert "sk-secret" not in dumped


def test_each_event_says_what_was_done_in_words(tmp_path: Path) -> None:
    """Every event carries an outcome, a plain kind name, and what its rule looks for."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {
                "event_type": "quarantine",
                "tool": "write_file",
                "rule_id": "petasos.syntactic.injection.ignore-previous",
                "severity": "HIGH",
            },
            {
                "event_type": "approval",
                "phase": "request",
                "tool": "terminal",
                "rule_id": "plugin_rule:petasos.syntactic.command.fetch-exec",
            },
            {
                "event_type": "approval",
                "phase": "response",
                "choice": "deny",
                "tool": "terminal",
                "rule_id": "plugin_rule:petasos.syntactic.command.fetch-exec",
            },
            {"event_type": "bypassed_disarmed", "tool": "terminal"},
            {"event_type": "block", "tool": "write_file", "tier": "tier2"},
        ],
    )
    events = _page(live)["events"]
    tier2, paused, answered, asked, blocked = events
    assert blocked["outcome"] == {"code": "blocked", "label": "Blocked"}
    assert blocked["kind_label"] == "Blocked tool call"
    # The sentence says what the agent tried to do; the tool's id is served beside it.
    assert blocked["summary"] == (
        "Blocked an attempt to write a file that contained hidden instructions."
    )
    assert "write_file" not in blocked["summary"]
    assert blocked["tool"] == "write_file"
    assert blocked["rule_sentence"].startswith("Looks for text that tells the agent to ignore")
    assert asked["outcome"]["code"] == "asked"
    assert asked["summary"] == "Asked a person before letting the agent run a shell command."
    assert asked["rule_sentence"] == "Looks for a command that downloads a script and runs it."
    assert answered["outcome"]["code"] == "declined"
    assert answered["summary"] == "A person did not let the agent run a shell command."
    assert paused["summary"].startswith("Let the agent run a shell command unchecked")
    assert paused["outcome"]["code"] == "allowed"
    assert paused["rule_sentence"] == ""
    assert tier2["summary"].endswith("warning signs in this conversation had added up.")
    assert tier2["risk_block"] is True
    assert blocked["risk_block"] is False


def _assert_figures_sum(summary: dict[str, Any]) -> None:
    assert sum(figure["count"] for figure in summary["figures"]) == summary["total"]
    assert all(figure["code"] != "not_stopped" for figure in summary["figures"])


def test_outcome_figures_add_up_for_a_mix_and_name_a_missing_severity(tmp_path: Path) -> None:
    """Every event is in one figure, and a dash is not a severity."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {
                "event_type": "quarantine",
                "severity": "HIGH",
                "rule_id": "petasos.syntactic.injection.ignore-previous",
            },
            {"event_type": "block", "tier": "tier2", "tool": "write_file"},
            {
                "event_type": "approval",
                "phase": "request",
                "rule_id": "plugin_rule:petasos.syntactic.command.fetch-exec",
                "tool": "terminal",
            },
            {"event_type": "bypassed_disarmed", "tool": "terminal"},
            {"event_type": "ingest_flagged", "severity": "medium", "rule_id": "r"},
            {
                "event_type": "selfmod_attempt",
                "rule_id": "petasos.selfmod.config-write",
                "severity": "critical",
                "tool": "write_file",
                "session_id": "calm",
            },
            {"event_type": "quarantine", "tool": "read_file", "session_id": "other"},
        ],
    )
    summary = summarize(live, _rot(live), key=None, verification=_OFF, query=ActivityQuery())
    _assert_figures_sum(summary)
    assert summary["total"] == 7
    finding = summary["finding"]
    assert finding is not None
    assert finding["count"] == 1
    assert finding["action"] == "Review current settings"
    assert "cannot show whether a change took effect" in finding["sentence"]
    other = next(figure for figure in summary["figures"] if figure["code"] == "other")
    assert other["outcomes"] == ["not_stopped"]
    page = _page(live)
    labels = {event["event_type"]: event["severity_label"] for event in page["events"]}
    assert labels["block"] == "Conversation risk"
    assert labels["approval"] == "Not recorded"
    assert labels["bypassed_disarmed"] == "No rule"
    quarantine = next(event for event in page["events"] if event.get("severity") == "HIGH")
    assert quarantine["severity_label"] == "High"
    attempt = next(event for event in page["events"] if event["event_type"] == "selfmod_attempt")
    assert attempt["review_action"] == "Review current settings"


def test_outcome_figures_add_up_for_an_arbitrary_mix(tmp_path: Path) -> None:
    """A second mix, with no guardrail finding, still partitions the total."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {"event_type": "tier3", "tool": "terminal"},
            {"event_type": "approval", "phase": "response", "choice": "deny"},
            {"event_type": "ingest_unscanned", "tool": "web_extract"},
            {"event_type": "cold_start_degraded", "tool": "terminal"},
        ],
    )
    summary = summarize(live, _rot(live), key=None, verification=_OFF, query=ActivityQuery())
    _assert_figures_sum(summary)
    assert summary["finding"] is None
    assert summary["total"] == 4
    codes = {figure["code"] for figure in summary["figures"]}
    assert "stopped" in codes
    assert "declined" in codes
    assert "unchecked" in codes
    assert "degraded" in codes


def test_summary_breaks_counts_down_for_filters(tmp_path: Path) -> None:
    """The summary lists tools, conversations and outcomes, and folds severity case."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {
                "event_type": "quarantine",
                "tool": "terminal",
                "session_id": "a",
                "severity": "HIGH",
            },
            {
                "event_type": "quarantine",
                "tool": "write_file",
                "session_id": "b",
                "severity": "high",
            },
            {"event_type": "ingest_flagged", "tool": "web_extract", "session_id": "a"},
        ],
    )
    summary = summarize(live, _rot(live), key=None, verification=_OFF, query=ActivityQuery())
    assert summary["by_severity"] == {"high": 2}
    assert summary["by_tool"] == {"terminal": 1, "write_file": 1, "web_extract": 1}
    assert summary["by_session"] == {"a": 2, "b": 1}
    assert summary["by_outcome"] == {"blocked": 2, "flagged": 1}
    assert summary["kind_labels"] == {
        "quarantine": "Blocked tool call",
        "ingest_flagged": "Tool result flagged",
    }
    page = _page(live, query=ActivityQuery(severity="high"))
    assert len(page["events"]) == 2


def _selfmod(session: str) -> dict[str, Any]:
    return {
        "event_type": "selfmod_attempt",
        "tool": "write_file",
        "session_id": session,
        "severity": "critical",
        "rule_id": "petasos.selfmod.config-write",
        "reason": "selfmod target: ~/.hermes/config.yaml",
    }


def test_a_guardrail_change_says_whether_the_call_was_stopped(tmp_path: Path) -> None:
    """Recording the attempt is not stopping it: the event after it for the same call decides."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            _selfmod("calm"),
            {"event_type": "quarantine", "tool": "read_file", "session_id": "calm"},
            _selfmod("hot"),
            {
                "event_type": "block",
                "tier": "tier2",
                "tool": "write_file",
                "session_id": "hot",
            },
        ],
    )
    events = _page(live)["events"]
    by_session = {
        event["session_id"]: event for event in events if event["event_type"] == "selfmod_attempt"
    }
    hot = by_session["hot"]
    assert hot["outcome"] == {"code": "attempt_blocked", "label": "Blocked"}
    assert "warning signs in this conversation had added up" in hot["summary"]
    assert hot["target"] == "~/.hermes/config.yaml"
    assert hot["risk_block"] is True
    calm = by_session["calm"]
    # The next event is for another tool, so it is not this call's outcome.
    assert calm["outcome"] == {"code": "not_stopped", "label": "Not stopped"}
    assert calm["summary"].startswith("Did not stop an attempt to change")
    assert calm["risk_block"] is False
    assert "cannot show whether the change took effect" in calm["outcome_note"]
    counts = summarize(live, _rot(live), key=None, verification=_OFF, query=ActivityQuery())[
        "by_outcome"
    ]
    assert counts["not_stopped"] == 1
    # Two blocks (the quarantine and the tier-2 block); the attempt is not a third.
    assert counts["blocked"] == 2
    assert counts["attempt_blocked"] == 1


def test_search_finds_an_event_by_id_start_or_words(tmp_path: Path) -> None:
    """``q`` matches the start of an event id, or the event's sentence and fields."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            {"event_type": "quarantine", "tool": "terminal", "session_id": "ops-1"},
            {"event_type": "approval", "phase": "request", "tool": "send_message"},
        ],
    )
    every = _page(live)["events"]
    wanted = every[1]["scan_id"]
    by_id = _page(live, query=ActivityQuery(text=wanted[:8]))["events"]
    assert [event["scan_id"] for event in by_id] == [wanted]
    by_word = _page(live, query=ActivityQuery(text="SHELL COMMAND"))["events"]
    assert [event["tool"] for event in by_word] == ["terminal"]
    assert _page(live, query=ActivityQuery(text="nothing like this"))["events"] == []


def test_each_event_says_what_its_signature_proves(tmp_path: Path) -> None:
    """A verified signature covers this entry and says it cannot show a deletion."""
    live = tmp_path / "petasos-enforcement.jsonl"
    secret = b"s" * 32
    _emit(live, [{"event_type": "quarantine", "tool": "terminal"}], secret=secret)
    signed = _page(live, key=verification_key(secret), verification="")["events"][0]
    assert signed["integrity"]["status"] == "verified"
    assert "cannot show whether other entries were deleted" in signed["integrity"]["meaning"]
    unsigned = _page(live)["events"][0]
    assert unsigned["integrity"]["status"] == "off"
    assert unsigned["integrity"]["meaning"].startswith("Not signed")


def test_the_blocked_count_agrees_with_the_rows_it_sits_above(tmp_path: Path) -> None:
    """A search can match a blocked attempt without the block written for the same call.

    The attempt still counts as one blocked call; when both match, the call counts once.
    """
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            _selfmod("calm"),
            {"event_type": "quarantine", "tool": "read_file", "session_id": "calm"},
            _selfmod("hot"),
            {"event_type": "block", "tier": "tier2", "tool": "write_file", "session_id": "hot"},
        ],
    )

    def counted(query: ActivityQuery) -> tuple[int, int, list[str]]:
        summary = summarize(live, _rot(live), key=None, verification=_OFF, query=query)
        rows = _page(live, query=query)["events"]
        assert summary["total"] == len(rows)
        return summary["total"], summary["blocked"], [row["outcome"]["label"] for row in rows]

    # The words of a guardrail attempt match both attempts and neither block.
    total, blocked, labels = counted(ActivityQuery(text="settings"))
    assert total == 2
    assert labels.count("Blocked") == 1
    assert blocked == 1
    # Everything: the hot call's attempt and its block are one blocked call.
    total, blocked, labels = counted(ActivityQuery())
    assert total == 4
    assert blocked == 2
    # One conversation, attempt and block together: still one call.
    total, blocked, labels = counted(ActivityQuery(session="hot"))
    assert (total, blocked) == (2, 1)


def test_an_outcome_filter_applies_to_the_page_and_the_counts(tmp_path: Path) -> None:
    """Filtering by outcome happens in the reader, so paging and counts agree with it."""
    live = tmp_path / "petasos-enforcement.jsonl"
    _emit(
        live,
        [
            _selfmod("calm"),
            {"event_type": "quarantine", "tool": "read_file", "session_id": "calm"},
            _selfmod("hot"),
            {"event_type": "block", "tier": "tier2", "tool": "write_file", "session_id": "hot"},
            {"event_type": "bypassed_disarmed", "tool": "terminal", "session_id": "calm"},
        ],
    )
    query = ActivityQuery(outcomes=("not_stopped",))
    page = _page(live, query=query)
    assert [event["outcome"]["code"] for event in page["events"]] == ["not_stopped"]
    summary = summarize(live, _rot(live), key=None, verification=_OFF, query=query)
    assert (summary["total"], summary["blocked"]) == (1, 0)
    blocked = ActivityQuery(outcomes=("blocked", "stopped", "attempt_blocked"))
    summary = summarize(live, _rot(live), key=None, verification=_OFF, query=blocked)
    assert (summary["total"], summary["blocked"]) == (3, 2)


def test_a_tool_petasos_cannot_name_keeps_its_id_in_the_sentence() -> None:
    """Known tools are named by what the agent tried to do; others by their id."""
    from petasos.hermes.dashboard.words import describe_event

    known = describe_event({"event_type": "quarantine", "tool": "send_message"})
    assert known == "Blocked an attempt to send a message."
    unknown = describe_event({"event_type": "quarantine", "tool": "mcp_lookup"})
    assert unknown == "Blocked a mcp_lookup call."
    flagged = describe_event(
        {
            "event_type": "ingest_flagged",
            "tool": "web_extract",
            "rule_id": "petasos.syntactic.injection.ignore-previous",
        }
    )
    assert flagged == "Warned the agent that a web page it read contained hidden instructions."
