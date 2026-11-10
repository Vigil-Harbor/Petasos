"""The tool-call decision ladder, with plain inputs and no host."""

from __future__ import annotations

import logging

from petasos._types import ScanFinding, Severity
from petasos.enforce.decisions import (
    Approve,
    Block,
    annotate_ingestion,
    approve_message,
    blocks,
    dangerous_tool_decision,
    guard_denial,
    is_dangerous,
    is_egress_sink,
    is_ingestion,
    match_source_namespace,
    normalize_posture,
    worst,
)
from petasos.enforce.messages import format_block_message, format_content_block
from petasos.session.guard import GuardResult

_READ_ONLY = frozenset({"read_file", "web_search"})
_SINKS = frozenset({"send_email"})
_NAMESPACES = frozenset({"mcp_", "mcp_bank_"})


def _finding(
    rule_id: str,
    *,
    finding_type: str = "injection",
    severity: Severity = Severity.HIGH,
    confidence: float = 0.9,
    message: str = "finding",
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type=finding_type,
        severity=severity,
        confidence=confidence,
        message=message,
        scanner_name="minimal",
    )


def _guard(
    *findings: ScanFinding,
    allowed: bool = True,
    tier: str = "none",
    reason: str = "allowed",
    degraded: bool = False,
    unsafe: bool = False,
) -> GuardResult:
    return GuardResult(
        allowed=allowed,
        reason=reason,
        findings=findings,
        tier=tier,
        param_scan_unsafe=unsafe or bool(findings) or degraded,
        param_scan_degraded=degraded,
    )


class _Store:
    def __init__(self, namespace: str | None) -> None:
        self.namespace = namespace

    def tainted_source(self, session_id: str, args: object) -> str | None:
        return self.namespace


def _decide(
    result: GuardResult,
    *,
    tool: str = "terminal",
    egress: bool = False,
    posture: str = "block",
    approve: bool = False,
    yolo: bool = False,
    always: set[str] | None = None,
    recorded: bool = False,
    tainted: str | None = None,
    namespaces: frozenset[str] = frozenset(),
    store: object | None = None,
) -> tuple[Block | Approve | None, list[str], list[dict[str, object]]]:
    logs: list[str] = []
    events: list[dict[str, object]] = []
    logger = logging.getLogger("petasos.enforce.test")

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logs.append(record.getMessage())

    handler = _Handler()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    approved = always or set()
    try:
        decision = dangerous_tool_decision(
            tool,
            {"command": "echo hi"},
            "sess",
            result,
            egress,
            posture,
            approve,
            yolo,
            namespaces=namespaces,
            taint_store=store,
            always_approved=approved.__contains__,
            degraded_recorded=lambda _session: recorded,
            excerpt_for=lambda: "echo hi",
            logger=logger,
            emit=lambda **fields: events.append(fields),
        )
    finally:
        logger.removeHandler(handler)
    return decision, logs, events


def test_blocks_high_and_critical_only() -> None:
    assert blocks(Severity.CRITICAL) is True
    assert blocks(Severity.HIGH) is True
    assert blocks(Severity.MEDIUM) is False
    assert blocks(Severity.LOW) is False
    assert blocks(Severity.INFO) is False


def test_worst_breaks_severity_ties_toward_confidence() -> None:
    low = _finding("a", confidence=0.2)
    high = _finding("b", confidence=0.8)
    assert worst((low, high)).rule_id == "b"
    critical = _finding("c", severity=Severity.CRITICAL, confidence=0.1)
    assert worst((high, critical)).rule_id == "c"


def test_tool_classification() -> None:
    assert is_dangerous("read_file", _READ_ONLY) is False
    assert is_dangerous("terminal", _READ_ONLY) is True
    assert is_dangerous("READ_FILE", _READ_ONLY) is False
    assert is_ingestion("read_file", frozenset({"memory"})) is True
    assert is_ingestion("memory", frozenset({"memory"})) is False
    assert is_ingestion("   ", frozenset()) is False
    assert is_egress_sink("Send_Email", _SINKS) is True
    assert is_egress_sink("terminal", _SINKS) is False
    assert match_source_namespace("mcp_bank_balance", _NAMESPACES) == "mcp_bank_"
    assert match_source_namespace("other", _NAMESPACES) is None


def test_posture_normalizes_to_approve_or_block() -> None:
    assert normalize_posture("approve") == "approve"
    assert normalize_posture("Approve") == "block"
    assert normalize_posture(None) == "block"
    assert normalize_posture("block") == "block"


def test_non_pii_blocks_before_an_approve_posture() -> None:
    finding = _finding("petasos.syntactic.injection.ignore")
    decision, logs, events = _decide(
        _guard(finding), posture="approve", approve=True, egress=False
    )
    assert isinstance(decision, Block)
    assert decision.message == format_content_block("non_pii_param", "terminal", (finding,))
    assert events[0]["event_type"] == "quarantine"
    assert events[0]["rule_id"] == finding.rule_id
    assert any("PETASOS_QUARANTINE" in line for line in logs)


def test_command_rule_approves_only_when_the_directive_is_usable() -> None:
    finding = _finding("petasos.syntactic.command.fetch-exec", finding_type="command")
    blocked, _, _ = _decide(_guard(finding), posture="approve", approve=False)
    assert isinstance(blocked, Block)
    approved, logs, events = _decide(_guard(finding), posture="approve", approve=True)
    assert isinstance(approved, Approve)
    assert approved.rule_key == finding.rule_id
    assert "echo hi" in approved.message
    assert events == []
    assert any("PETASOS_APPROVE" in line for line in logs)
    yolo, _, _ = _decide(_guard(finding), posture="approve", approve=True, yolo=True)
    assert isinstance(yolo, Block)
    waived, _, _ = _decide(
        _guard(finding),
        posture="approve",
        approve=True,
        always={finding.rule_id},
    )
    assert waived is None


def test_degraded_scan_ladder() -> None:
    result = _guard(degraded=True)
    blocked, _, events = _decide(result, posture="block", approve=True)
    assert isinstance(blocked, Block)
    assert "fail-mode policy" in blocked.message
    assert events[0]["param_scan_degraded"] is True

    asked, _, _ = _decide(result, posture="approve", approve=True)
    assert isinstance(asked, Approve)
    assert asked.rule_key == "petasos.degraded"
    assert "unreliable" in asked.message

    absent, _, _ = _decide(result, posture="approve", approve=False)
    assert isinstance(absent, Block)
    auto, _, _ = _decide(result, posture="approve", approve=True, yolo=True)
    assert isinstance(auto, Block)
    recorded, _, _ = _decide(result, posture="approve", approve=True, recorded=True)
    assert recorded is None
    always, _, _ = _decide(result, posture="approve", approve=True, always={"petasos.degraded"})
    assert always is None


def test_taint_blocks_ahead_of_pii_and_pii_blocks_only_on_egress() -> None:
    pii = _finding("pii.email", finding_type="pii", severity=Severity.CRITICAL)
    tainted, _, events = _decide(
        _guard(pii),
        tool="send_email",
        egress=True,
        namespaces=_NAMESPACES,
        store=_Store("mcp_bank_"),
    )
    assert isinstance(tainted, Block)
    assert tainted.message == format_content_block("taint_egress", "send_email", ())
    assert events[0]["reason"] == "source-taint egress: mcp_bank_ -> send_email"

    leaked, _, _ = _decide(_guard(pii), tool="send_email", egress=True)
    assert isinstance(leaked, Block)
    assert "Sensitive data" in leaked.message
    kept, _, kept_events = _decide(_guard(pii), tool="terminal", egress=False)
    assert kept is None
    assert kept_events == []


def test_guard_denial_covers_tier3_and_tier2() -> None:
    events: list[dict[str, object]] = []
    logger = logging.getLogger("petasos.enforce.test.guard")
    tier3 = _guard(allowed=False, tier="tier3", reason="session terminated (tier3)")
    decision = guard_denial(
        "read_file", "sess", tier3, logger=logger, emit=lambda **fields: events.append(fields)
    )
    assert isinstance(decision, Block)
    assert decision.message == format_block_message(tier3, "read_file")
    assert events[0]["event_type"] == "tier3"
    allowed = _guard()
    assert (
        guard_denial("read_file", "sess", allowed, logger=logger, emit=lambda **_fields: None)
        is None
    )


def _must_not_emit(**_fields: object) -> None:
    raise AssertionError("caller emits")


def test_ingestion_annotation_paths() -> None:
    finding = _finding("petasos.syntactic.injection.ignore")
    events: list[dict[str, object]] = []
    logger = logging.getLogger("petasos.enforce.test.ingest")
    flagged = annotate_ingestion(
        "read_file",
        "payload",
        (finding,),
        cause=None,
        regime="full",
        scanned_chars=7,
        total_chars=7,
        session_id="sess",
        logger=logger,
        emit=lambda **fields: events.append(fields),
    )
    assert flagged is not None
    assert flagged.startswith("[Petasos]")
    assert flagged.endswith("payload")
    assert events[0]["event_type"] == "ingest_flagged"

    pii = _finding("pii.email", finding_type="pii")
    assert (
        annotate_ingestion(
            "read_file",
            "payload",
            (pii,),
            cause=None,
            regime="full",
            scanned_chars=7,
            total_chars=7,
            session_id="sess",
            logger=logger,
            emit=lambda **_fields: None,
        )
        is None
    )
    unavailable = annotate_ingestion(
        "read_file",
        "payload",
        (),
        cause="timeout",
        regime=None,
        scanned_chars=0,
        total_chars=0,
        session_id="sess",
        logger=logger,
        emit=_must_not_emit,
    )
    assert unavailable is not None
    assert "could not scan" in unavailable
    ceiling = annotate_ingestion(
        "read_file",
        "payload",
        (),
        cause=None,
        regime="ceiling",
        scanned_chars=10,
        total_chars=20,
        session_id="sess",
        logger=logger,
        emit=lambda **_fields: None,
    )
    assert ceiling is not None
    assert "Coverage: ceiling." in ceiling


def test_approve_message_names_the_rule() -> None:
    text = approve_message("terminal", "petasos.syntactic.command.fetch-exec", "echo")
    assert "fetch-exec" in text
    assert "echo" in text
    degraded = approve_message("terminal", "petasos.degraded", "echo")
    assert "unreliable" in degraded
