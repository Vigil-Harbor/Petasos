"""Excerpt redaction and approval observation, without a host."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petasos.enforce.approvals import (
    approval_choice,
    approval_event,
    approval_pattern_keys,
    approval_session_id,
    approval_text,
    command_excerpt,
    credential_reason,
    degraded_choice_confirmed,
    degraded_pending_key,
    is_degraded_pattern,
    redact_display_text,
    redaction_status,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_NOTICE = "Sensitive content masked locally; exposure unconfirmed."


def _redact(text: str, **_options: bool) -> str:
    return text.replace("secret-value", "[MASKED]")


def _result(finding_type: str | None = None) -> object:
    if finding_type is None:
        return type("Result", (), {"findings": ()})()
    finding = type("Finding", (), {"finding_type": finding_type})()
    return type("Result", (), {"findings": (finding,)})()


def test_excerpt_redacts_and_withholds() -> None:
    shown = command_excerpt(
        {"command": "echo secret-value"},
        _result(),
        load_redactor=lambda: _redact,
    )
    assert "secret-value" not in shown
    assert "[MASKED]" in shown
    assert _NOTICE in shown

    pii = command_excerpt({"command": "echo"}, _result("pii"), load_redactor=lambda: _redact)
    assert pii == "withheld (PII in parameters)"
    assert command_excerpt({}, _result(), load_redactor=lambda: _redact) == "(no parameters)"

    def _missing() -> Callable[..., str]:
        raise ImportError("no host")

    missing = command_excerpt(
        {"command": "echo"},
        _result(),
        load_redactor=_missing,
    )
    assert missing == "withheld (redactor unavailable)"


def test_excerpt_drops_invisible_characters() -> None:
    shown = command_excerpt(
        {"command": "echo\u2066"},
        _result(),
        load_redactor=lambda: lambda text, **_options: text,
    )
    assert "\u2066" not in shown
    assert "invisible characters removed" in shown


def test_display_redaction_and_reason() -> None:
    text, status = redact_display_text("secret-value", 200, redact=_redact)
    assert text == "[MASKED]"
    assert status == "redacted"
    assert credential_reason("approval requested", status).startswith(_NOTICE)
    empty, unchanged = redact_display_text("", 20, redact=None)
    assert (empty, unchanged) == ("", "unchanged")
    withheld, state = redact_display_text("visible", 20, redact=None)
    assert state == "withheld"
    assert withheld.startswith("withheld")
    assert redaction_status({"unchanged", "redacted"}) == "redacted"
    assert redaction_status({"redacted", "withheld"}) == "withheld"


def test_approval_fields_and_event() -> None:
    assert approval_text("x" * 10, limit=4) == "xxxx"
    assert approval_text(3) == ""
    assert approval_pattern_keys(["a", 1, "b"] + ["c"] * 20) == ["a", "b", *["c"] * 6]
    assert len(approval_pattern_keys(["a"] * 9)) == 8
    assert approval_session_id("", "key") == "key"
    assert approval_session_id("sid", "key") == "sid"
    assert approval_choice("request", "allow") is None
    assert approval_choice("response", None) is None
    assert approval_choice("response", "once") == "once"

    event = approval_event(
        "response",
        choice="once",
        armed=True,
        command="terminal",
        description="run it",
        redaction="unchanged",
        fields={
            "pattern_key": "plugin_rule:petasos.degraded",
            "command": "<terminal> (plugin approval rule)",
            "session_id": "sess",
            "surface": "cli",
        },
    )
    assert event["event_type"] == "approval"
    assert event["phase"] == "response"
    assert event["choice"] == "once"
    assert event["tool"] == "terminal"
    assert event["session_id"] == "sess"
    assert event["reason"] == "approval response"
    assert event["armed"] is True


def test_degraded_pending_key() -> None:
    assert degraded_pending_key("s", "t", "c") == ("s", "t", "c")
    assert degraded_pending_key("", "t", "c") is None
    assert degraded_pending_key("s", None, "c") is None
    assert degraded_choice_confirmed("session") is True
    assert degraded_choice_confirmed("always") is True
    assert degraded_choice_confirmed("once") is False
    assert is_degraded_pattern("plugin_rule:petasos.degraded") is True
    assert is_degraded_pattern("other") is False
