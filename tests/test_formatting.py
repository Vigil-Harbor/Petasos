from __future__ import annotations

from petasos._types import PipelineResult, ScanFinding, Severity
from petasos.session.formatting import (
    format_block_message,
    format_pipeline_block_message,
    shorten_rule_id,
)
from petasos.session.guard import GuardResult

_PREFIX = "[BLOCKED by Petasos]"

_INTERNAL_REASONS = [
    "session terminated (tier3)",
    "tier2: tool calls blocked",
    "invalid tool name: empty after normalization",
    "exempt-with-scan",
    "tool exempt per profile",
    "tier1: allowed with warnings",
    "allowed",
    "feature disabled",
]


def _finding(
    *,
    rule_id: str = "petasos.syntactic.injection.ignore-previous",
    severity: Severity = Severity.HIGH,
    message: str = "Injection pattern matched: ignore-previous",
) -> ScanFinding:
    return ScanFinding(
        rule_id=rule_id,
        finding_type="injection",
        severity=severity,
        confidence=0.95,
        message=message,
        scanner_name="minimal",
    )


def _guard(
    *,
    allowed: bool = False,
    reason: str = "blocked",
    findings: tuple[ScanFinding, ...] = (),
    tier: str = "none",
    param_scan_unsafe: bool = False,
) -> GuardResult:
    return GuardResult(
        allowed=allowed,
        reason=reason,
        findings=findings,
        tier=tier,
        param_scan_unsafe=param_scan_unsafe,
    )


class TestTier3BlockMessage:
    def test_tier3_block_message(self) -> None:
        result = _guard(tier="tier3", reason="session terminated (tier3)")
        msg = format_block_message(result, "terminal")

        assert _PREFIX in msg
        assert "'terminal'" in msg
        assert "was NOT executed" in msg
        assert "tier3" in msg
        assert "All tool calls are blocked" in msg
        assert "Top finding" not in msg


class TestTier2BlockMessage:
    def test_tier2_block_message(self) -> None:
        result = _guard(
            tier="tier2",
            reason="tier2: tool calls blocked",
            findings=(_finding(),),
        )
        msg = format_block_message(result, "terminal")

        assert _PREFIX in msg
        assert "'terminal'" in msg
        assert "was NOT executed" in msg
        assert "tier2" in msg
        assert "injection.ignore-previous" in msg
        assert "(HIGH)" in msg
        assert "Injection pattern matched" in msg


class TestInvalidToolNameBlockMessage:
    def test_invalid_tool_name_block_message(self) -> None:
        result = _guard(reason="invalid tool name: empty after normalization")
        msg = format_block_message(result, "")

        assert _PREFIX in msg
        assert "tool name invalid" in msg
        assert "was NOT executed" in msg


class TestParamScanUnsafe:
    def test_param_scan_unsafe_block_message(self) -> None:
        result = _guard(
            allowed=False,
            reason="tier2: tool calls blocked",
            param_scan_unsafe=True,
            findings=(_finding(),),
            tier="tier2",
        )
        msg = format_block_message(result, "bash")

        assert _PREFIX in msg
        assert "was NOT executed" in msg

    def test_param_scan_unsafe_allowed_true(self) -> None:
        result = _guard(
            allowed=True,
            reason="exempt-with-scan",
            param_scan_unsafe=True,
            findings=(_finding(),),
        )
        msg = format_block_message(result, "bash")

        assert _PREFIX in msg
        assert "'bash'" in msg
        assert "was NOT executed" in msg
        assert "Injection pattern detected in parameters" in msg
        assert "injection.ignore-previous" in msg


class TestCatchAllBlock:
    def test_catch_all_block_unknown_reason(self) -> None:
        result = _guard(allowed=False, reason="future_reason", findings=(_finding(),))
        msg = format_block_message(result, "custom_tool")

        assert _PREFIX in msg
        assert "'custom_tool'" in msg
        assert "was NOT executed" in msg
        assert "injection.ignore-previous" in msg


class TestPipelineBlockMessage:
    def test_pipeline_block_message(self) -> None:
        result = PipelineResult(safe=False, findings=(_finding(),))
        msg = format_pipeline_block_message(result)

        assert _PREFIX in msg
        assert "Message blocked" in msg
        assert "not forwarded" in msg
        assert "injection.ignore-previous" in msg

    def test_pipeline_safe_returns_empty(self) -> None:
        result = PipelineResult(safe=True, findings=())
        assert format_pipeline_block_message(result) == ""


class TestNoBlockReturnsEmpty:
    def test_allowed_no_unsafe_returns_empty(self) -> None:
        result = _guard(allowed=True, reason="allowed", param_scan_unsafe=False)
        assert format_block_message(result, "read") == ""

    def test_tier1_no_unsafe_returns_empty(self) -> None:
        result = _guard(
            allowed=True,
            reason="tier1: allowed with warnings",
            tier="tier1",
            param_scan_unsafe=False,
        )
        assert format_block_message(result, "read") == ""


class TestShortenRuleId:
    def test_strips_prefix(self) -> None:
        assert (
            shorten_rule_id("petasos.syntactic.injection.ignore-previous")
            == "injection.ignore-previous"
        )

    def test_passthrough(self) -> None:
        assert shorten_rule_id("llm_guard.threat") == "llm_guard.threat"


class TestTopFindingSelection:
    def test_selects_highest_severity(self) -> None:
        findings = (
            _finding(
                severity=Severity.LOW,
                rule_id="petasos.syntactic.encoding.base64-in-text",
                message="Low",
            ),
            _finding(
                severity=Severity.CRITICAL,
                rule_id="petasos.syntactic.structural.oversized-payload",
                message="Critical",
            ),
            _finding(severity=Severity.HIGH, message="High"),
        )
        result = _guard(
            findings=findings, param_scan_unsafe=True, allowed=True, reason="exempt-with-scan"
        )
        msg = format_block_message(result, "bash")

        assert "structural.oversized-payload" in msg
        assert "(CRITICAL)" in msg

    def test_additional_findings_count_plural(self) -> None:
        findings = (
            _finding(),
            _finding(severity=Severity.MEDIUM, message="m1"),
            _finding(severity=Severity.LOW, message="m2"),
        )
        result = _guard(
            findings=findings, param_scan_unsafe=True, allowed=True, reason="exempt-with-scan"
        )
        msg = format_block_message(result, "bash")

        assert "(+2 additional findings)" in msg

    def test_additional_findings_count_singular(self) -> None:
        findings = (_finding(), _finding(severity=Severity.LOW, message="m1"))
        result = _guard(
            findings=findings, param_scan_unsafe=True, allowed=True, reason="exempt-with-scan"
        )
        msg = format_block_message(result, "bash")

        assert "(+1 additional finding)" in msg

    def test_no_findings_no_clause(self) -> None:
        result = _guard(tier="tier2", reason="tier2: tool calls blocked")
        msg = format_block_message(result, "bash")

        assert "Top finding" not in msg


class TestInternalReasonStrings:
    def test_internal_reason_strings_not_in_output(self) -> None:
        cases = [
            _guard(tier="tier3", reason="session terminated (tier3)"),
            _guard(tier="tier2", reason="tier2: tool calls blocked", findings=(_finding(),)),
            _guard(reason="invalid tool name: empty after normalization"),
            _guard(
                allowed=True,
                reason="exempt-with-scan",
                param_scan_unsafe=True,
                findings=(_finding(),),
            ),
            _guard(allowed=False, reason="future_reason"),
        ]
        for gr in cases:
            msg = format_block_message(gr, "tool")
            for reason in _INTERNAL_REASONS:
                assert reason not in msg, f"Internal string {reason!r} leaked in: {msg}"


class TestMessageLimits:
    def test_worst_case_under_200_words(self) -> None:
        long_message = "A" * 500
        findings = tuple(
            _finding(message=long_message, severity=s)
            for s in [Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO, Severity.INFO]
        )
        result = _guard(tier="tier2", reason="tier2: tool calls blocked", findings=findings)
        msg = format_block_message(result, "terminal")

        assert len(msg.split()) < 200

    def test_long_finding_message_truncated(self) -> None:
        long_message = "X" * 500
        result = _guard(
            param_scan_unsafe=True,
            allowed=True,
            reason="exempt-with-scan",
            findings=(_finding(message=long_message),),
        )
        msg = format_block_message(result, "bash")

        assert "X" * 200 in msg
        assert "…" in msg
        assert "X" * 201 not in msg

    def test_severity_displayed_uppercase(self) -> None:
        result = _guard(
            param_scan_unsafe=True,
            allowed=True,
            reason="exempt-with-scan",
            findings=(_finding(severity=Severity.HIGH),),
        )
        msg = format_block_message(result, "bash")

        assert "(HIGH)" in msg
        assert "(high)" not in msg
