"""Cold-start and init-failure decisions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from petasos._types import ScanFinding, Severity

if TYPE_CHECKING:
    import pytest
from petasos.enforce.decisions import Block
from petasos.enforce.fallback import (
    FallbackScan,
    fallback_decision,
    scan_fallback,
    tier3_unavailable_block,
)
from petasos.enforce.messages import format_block_message, format_content_block
from petasos.session.guard import PARAM_SCAN_DIRECTION, GuardResult


class _Result:
    def __init__(self, findings: tuple[ScanFinding, ...] = (), error: str | None = None) -> None:
        self.findings = findings
        self.error = error


class _Scanner:
    def __init__(self, result: _Result) -> None:
        self.result = result
        self.direction: str | None = None

    def scan(self, text: str, direction: str | None = None) -> _Result:
        self.direction = direction
        return self.result


def _finding() -> ScanFinding:
    return ScanFinding(
        rule_id="petasos.syntactic.injection.ignore",
        finding_type="injection",
        severity=Severity.HIGH,
        confidence=1.0,
        message="ignore previous",
        scanner_name="minimal",
    )


def _scan(
    tool: str,
    args: dict[str, object],
    scanner: _Scanner,
    *,
    dangerous: bool = True,
    boom: bool = False,
) -> tuple[FallbackScan, list[dict[str, object]]]:
    events: list[dict[str, object]] = []

    def is_dangerous(name: str) -> bool:
        if boom:
            raise TypeError(name)
        return dangerous

    scanned = scan_fallback(
        tool,
        args,
        is_dangerous=is_dangerous,
        session_id_for=lambda: "sess",
        scanner_for=lambda: scanner,
        run=lambda value: value,
        logger=logging.getLogger("petasos.enforce.test.fallback"),
        emit=lambda **fields: events.append(fields),
    )
    return scanned, events


def test_read_only_is_skipped_and_a_finding_blocks() -> None:
    scanner = _Scanner(_Result((_finding(),)))
    skipped, events = _scan("read_file", {"path": "a"}, scanner, dangerous=False)
    assert skipped.outcome == "skipped"
    assert skipped.block is None
    assert events == []
    assert scanner.direction is None

    blocked, events = _scan("terminal", {"command": "echo hi"}, scanner)
    assert blocked.outcome == "blocked"
    assert isinstance(blocked.block, Block)
    assert blocked.block.message == format_content_block("init", "terminal", (_finding(),))
    assert scanner.direction == PARAM_SCAN_DIRECTION
    assert events[0]["event_type"] == "quarantine"
    assert events[0]["rule_id"] == "petasos.syntactic.injection.ignore"


def test_scan_error_and_exception_are_errored_without_a_block() -> None:
    scanner = _Scanner(_Result(error="boom"))
    errored, _events = _scan("terminal", {"command": "echo hi"}, scanner)
    assert errored.outcome == "errored"
    assert errored.block is None

    empty, _events = _scan("terminal", {}, _Scanner(_Result()))
    assert empty.outcome == "clean"

    def explode(_name: str) -> bool:
        raise RuntimeError("nope")

    try:
        scan_fallback(
            "terminal",
            {"command": "echo"},
            is_dangerous=explode,
            session_id_for=lambda: "sess",
            scanner_for=lambda: _Scanner(_Result()),
            run=lambda value: value,
            logger=logging.getLogger("petasos.enforce.test.fallback"),
            emit=lambda **_fields: None,
        )
    except RuntimeError as exc:
        assert str(exc) == "nope"
    else:
        raise AssertionError("an unclassifiable name must propagate")


def test_fail_mode_allows_only_a_clean_open_scan() -> None:
    events: list[dict[str, object]] = []

    def decide(outcome: str | None, fail_mode: object, *, dangerous: bool = True) -> Block | None:
        return fallback_decision(
            "terminal",
            outcome,
            session_id="sess",
            log_cause="cold window",
            block_reason="cold-window block",
            fail_mode=fail_mode,
            is_dangerous=lambda _name: dangerous,
            logger=logging.getLogger("petasos.enforce.test.fallback"),
            emit=lambda **fields: events.append(fields),
        )

    assert decide("clean", "open") is None
    for mode in ("degraded", "closed", "nope", None):
        decision = decide("clean", mode)
        assert isinstance(decision, Block)
        assert "fail-mode policy" in decision.message
    errored = decide("errored", "open")
    assert isinstance(errored, Block)
    assert decide("clean", "closed", dangerous=False) is None
    assert any(event["reason"] == "cold-window block" for event in events)


def _raise_type_error(_name: str) -> bool:
    raise TypeError("bad")


def test_unclassifiable_name_fails_secure() -> None:
    decision = fallback_decision(
        "terminal",
        "errored",
        session_id="sess",
        log_cause="init failed",
        block_reason="init-failed block",
        fail_mode="open",
        is_dangerous=_raise_type_error,
        logger=logging.getLogger("petasos.enforce.test.fallback"),
        emit=lambda **_fields: None,
    )
    assert isinstance(decision, Block)
    allowed = fallback_decision(
        "terminal",
        "clean",
        session_id="sess",
        log_cause="init failed",
        block_reason="init-failed block",
        fail_mode="open",
        is_dangerous=_raise_type_error,
        logger=logging.getLogger("petasos.enforce.test.fallback"),
        emit=lambda **_fields: None,
    )
    assert allowed is None


def test_tier3_unavailable_block_uses_the_guard_message() -> None:
    events: list[dict[str, object]] = []
    decision = tier3_unavailable_block(
        "read_file",
        "sess",
        logger=logging.getLogger("petasos.enforce.test.fallback"),
        emit=lambda **fields: events.append(fields),
    )
    expected = format_block_message(
        GuardResult(
            allowed=False,
            reason="session terminated (tier3)",
            findings=(),
            tier="tier3",
            param_scan_unsafe=False,
        ),
        "read_file",
    )
    assert decision.message == expected
    assert events[0]["event_type"] == "tier3"


def test_a_truncated_parameter_is_logged_and_a_raising_scan_is_errored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from petasos._limits import MAX_PARAM_TEXT_LEN

    logger_name = "petasos.enforce.test.fallback"
    scanner = _Scanner(_Result())
    with caplog.at_level(logging.WARNING, logger=logger_name):
        scanned, _events = _scan(
            "terminal",
            {"command": "x" * (MAX_PARAM_TEXT_LEN + 1)},
            scanner,
        )
    assert scanned.outcome == "clean"
    assert any("PETASOS_PARAM_TRUNCATED" in record.getMessage() for record in caplog.records)

    class _Raising:
        def scan(self, text: str, direction: str | None = None) -> _Result:
            raise RuntimeError("scan failed")

    failed, _events = _scan("terminal", {"command": "echo"}, _Raising())  # type: ignore[arg-type]
    assert failed.outcome == "errored"
    assert failed.block is None
