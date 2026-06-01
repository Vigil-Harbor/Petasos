from __future__ import annotations

from typing import TYPE_CHECKING

from petasos._types import PipelineResult, ScanFinding, Severity

if TYPE_CHECKING:
    from petasos.session.guard import GuardResult

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

_STRIP_PREFIX = "petasos.syntactic."

_PREFIX = "[BLOCKED by Petasos]"

_MAX_MESSAGE_LEN = 200


def shorten_rule_id(rule_id: str) -> str:
    if rule_id.startswith(_STRIP_PREFIX):
        return rule_id[len(_STRIP_PREFIX) :]
    return rule_id


def _top_finding_clause(findings: tuple[ScanFinding, ...]) -> str:
    if not findings:
        return ""

    top = min(findings, key=lambda f: _SEVERITY_RANK.get(f.severity, 999))

    short_id = shorten_rule_id(top.rule_id)
    severity = top.severity.name

    message = top.message
    if len(message) > _MAX_MESSAGE_LEN:
        message = message[:_MAX_MESSAGE_LEN] + "…"

    clause = f'Top finding: {short_id} ({severity}) — "{message}".'

    extra = len(findings) - 1
    if extra == 1:
        clause += " (+1 additional finding)"
    elif extra > 1:
        clause += f" (+{extra} additional findings)"

    return clause


def format_block_message(result: GuardResult, tool_name: str) -> str:
    if result.tier == "tier3":
        return (
            f"{_PREFIX} Tool '{tool_name}' was NOT executed. "
            "Session terminated (tier3) — escalation threshold exceeded. "
            "All tool calls are blocked for this session."
        )

    if not result.allowed and result.tier == "tier2":
        clause = _top_finding_clause(result.findings)
        msg = (
            f"{_PREFIX} Tool '{tool_name}' was NOT executed."
            " Session under enhanced scrutiny (tier2)."
        )
        if clause:
            msg += " " + clause
        return msg

    if not result.allowed and "invalid tool name" in result.reason:
        return (
            f"{_PREFIX} Tool call rejected — tool name invalid "
            "after normalization. Call was NOT executed."
        )

    if result.param_scan_unsafe:
        clause = _top_finding_clause(result.findings)
        msg = (
            f"{_PREFIX} Tool '{tool_name}' was NOT executed. "
            "Injection pattern detected in parameters."
        )
        if clause:
            msg += " " + clause
        return msg

    if not result.allowed:
        clause = _top_finding_clause(result.findings)
        msg = f"{_PREFIX} Tool '{tool_name}' was NOT executed."
        if clause:
            msg += " " + clause
        return msg

    return ""


def format_pipeline_block_message(result: PipelineResult) -> str:
    if result.safe:
        return ""

    clause = _top_finding_clause(result.findings)
    msg = f"{_PREFIX} Message blocked — content not forwarded."
    if clause:
        msg += " " + clause
    return msg
