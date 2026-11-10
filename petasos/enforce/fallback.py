"""The syntactic-only gate used before the pipeline is ready, and after it fails.

The gate scans dangerous-tool parameters with one scanner. The decision under
each fail mode is separate: only ``open`` can allow a dangerous call, and only
when that scan came back clean.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from petasos.enforce.decisions import Block, blocks, worst
from petasos.enforce.messages import format_block_message, format_content_block
from petasos.session.guard import (
    PARAM_SCAN_DIRECTION,
    GuardResult,
    render_param_text,
)

if TYPE_CHECKING:
    import logging

_Emit = Callable[..., object]
_Run = Callable[[Any], Any]
_Dangerous = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class FallbackScan:
    """What the syntactic gate did.

    ``outcome`` is ``skipped``, ``clean``, ``errored``, or ``blocked``.
    ``block`` is set only for ``blocked``.
    """

    outcome: str
    block: Block | None


def scan_fallback(
    tool_name: str,
    args: Mapping[str, Any],
    *,
    is_dangerous: _Dangerous,
    session_id_for: Callable[[], str],
    scanner_for: Callable[[], Any],
    run: _Run,
    logger: logging.Logger,
    emit: _Emit,
) -> FallbackScan:
    """Scan one dangerous tool's parameters, or skip a read-only tool.

    ``is_dangerous`` is called outside the scan's own error boundary, so an
    unclassifiable name propagates. A scan that raises, or a scan result that
    carries an error and no blocking finding, is ``errored`` and returns no
    block. A blocking finding returns ``blocked`` and has already been logged
    and emitted.
    """
    if not is_dangerous(tool_name):
        return FallbackScan("skipped", None)
    try:
        session_id = session_id_for()
        scanner = scanner_for()
        rendered = render_param_text(args)
        if rendered.truncated:
            logger.warning(
                "PETASOS_PARAM_TRUNCATED tool=%s session=%s len=%d scanned=%d",
                tool_name,
                session_id,
                rendered.original_len,
                len(rendered.text),
            )
        if not rendered.text:
            return FallbackScan("clean", None)
        result = run(scanner.scan(rendered.text, direction=PARAM_SCAN_DIRECTION))
        if result.findings:
            top = worst(result.findings)
            if blocks(top.severity):
                logger.warning(
                    "PETASOS_FALLBACK_BLOCK tool=%s — syntactic fallback, scan found: %s",
                    tool_name,
                    top.rule_id,
                )
                emit(
                    session_id=session_id,
                    tool=tool_name,
                    event_type="quarantine",
                    severity=top.severity.name,
                    rule_id=top.rule_id,
                    reason=top.message,
                )
                return FallbackScan(
                    "blocked",
                    Block(format_content_block("init", tool_name, tuple(result.findings))),
                )
        if result.error is not None:
            logger.warning(
                "PETASOS_FALLBACK_SCAN_ERROR tool=%s error=%r",
                tool_name,
                result.error,
            )
            return FallbackScan("errored", None)
    except Exception as exc:
        logger.warning(
            "PETASOS_FALLBACK_SCAN_ERROR tool=%s error=%r",
            tool_name,
            str(exc),
        )
        return FallbackScan("errored", None)
    return FallbackScan("clean", None)


def fallback_decision(
    tool_name: str,
    outcome: str | None,
    *,
    session_id: str,
    log_cause: str,
    block_reason: str,
    fail_mode: object,
    is_dangerous: _Dangerous,
    logger: logging.Logger,
    emit: _Emit,
) -> Block | None:
    """Block a dangerous call the syntactic gate did not already block.

    Only ``fail_mode == "open"`` can allow one, and only when ``outcome`` is
    ``clean``. Any other fail mode, including a missing or unrecognized value,
    blocks. An unclassifiable tool name is treated as dangerous. A read-only
    tool is allowed before the outcome is read. ``None`` means allow.
    """
    try:
        dangerous = is_dangerous(tool_name)
    except Exception:
        dangerous = True  # an unclassifiable name fails secure, it does not raise
    if not dangerous:
        return None
    if outcome == "clean" and fail_mode == "open":
        return None
    logger.warning(
        "PETASOS_QUARANTINE tool=%s session=%s — %s, scan outcome=%s",
        tool_name,
        session_id,
        log_cause,
        outcome if outcome in ("clean", "errored") else "unreadable",
    )
    emit(
        session_id=session_id,
        tool=tool_name,
        event_type="quarantine",
        param_scan_degraded=True,
        reason=block_reason,
    )
    return Block(format_content_block("degraded", tool_name, ()))


def tier3_unavailable_block(
    tool_name: str,
    session_id: str,
    *,
    logger: logging.Logger,
    emit: _Emit,
) -> Block:
    """Block every tool when a failed evaluation finds a terminated session."""
    logger.critical(
        "PETASOS_TIER3 tool=%s session=%s — all tool calls blocked", tool_name, session_id
    )
    emit(session_id=session_id, tool=tool_name, event_type="tier3", tier="tier3")
    message = format_block_message(
        GuardResult(
            allowed=False,
            reason="session terminated (tier3)",
            findings=(),
            tier="tier3",
            param_scan_unsafe=False,
        ),
        tool_name,
    )
    return Block(message)
