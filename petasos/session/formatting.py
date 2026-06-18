from __future__ import annotations

from typing import TYPE_CHECKING, Literal

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

# PET-77: the reference-plugin content-scan / init-fallback block sites fire after the
# guard has returned allowed=True (or operate outside GuardResult), so they cannot reuse
# format_block_message. format_content_block is keyed on the block decision the shim
# already made (one of these paths) plus the findings that drove it.
ContentBlockPath = Literal["init", "degraded", "non_pii_param", "pii_egress", "taint_egress"]

_CONTENT_REASON: dict[str, str] = {
    "init": "Blocked by the initialization-time security scan.",
    "degraded": "Parameter scan unavailable (scanner degraded); blocked by fail-mode policy.",
    "non_pii_param": "Unsafe content detected in the tool parameters.",
    "pii_egress": "Sensitive data (PII) was about to leave via this tool; the call was stopped.",
    # PET-134: the model-facing taint message carries NO source/sink detail (PET-77:
    # internal provenance reasons never reach the model; that detail goes only to the
    # operator log + enforcement event).
    "taint_egress": (
        "Content from a restricted source was about to leave via this tool; the call was stopped."
    ),
}


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


def format_content_block(
    path: ContentBlockPath,
    tool_name: str,
    findings: tuple[ScanFinding, ...],
) -> str:
    """Format a model-facing block message for a reference-plugin content-scan or
    init-fallback block.

    Keyed on the block decision the shim already made (``path``) plus the findings
    that drove it, because these sites fire after the guard has returned
    ``allowed=True`` (or outside ``GuardResult`` entirely) and so cannot reuse
    ``format_block_message`` (which returns ``""`` for an allowed result).

    The reason lookup is fail-closed: an out-of-set ``path`` (a wiring typo in a
    caller that mypy does not type-check at the import boundary) degrades to a valid
    ``[BLOCKED by Petasos]`` message rather than raising, honoring the
    pipeline-never-throws invariant.
    """
    reason = _CONTENT_REASON.get(path, "Blocked by a security policy.")
    clause = _top_finding_clause(findings)
    msg = f"{_PREFIX} Tool '{tool_name}' was NOT executed. {reason}"
    if clause:
        msg += " " + clause
    return msg
