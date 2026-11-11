"""What to do with a tool call once the guard has evaluated it.

A decision is plain data. The host turns it into a hook result, records it, and
supplies the facts only the host knows: whether an approve directive exists,
whether auto-approve is on, and whether a rule was always approved.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from petasos.enforce.messages import (
    format_block_message,
    format_content_block,
    format_result_notice,
)
from petasos.model import ScanFinding, Severity, at_least, severity_rank
from petasos.normalize import canonicalize_tool_name

if TYPE_CHECKING:
    import logging

    from petasos.session.guard import GuardResult

COMMAND_RULE_PREFIX = "petasos.syntactic.command."
RESULT_SCAN_ERROR_REASON = "result scan unavailable"

_Emit = Callable[..., object]
_Always = Callable[[str], bool]
_Recorded = Callable[[str], bool]
_Excerpt = Callable[[], str]
_Asks = Callable[[str], bool]
_Regime = Literal["full", "ceiling"]


def _not_asked(_command: str) -> bool:
    return False


def _command_text(args: Any) -> str:
    if isinstance(args, Mapping):
        raw = args.get("command")
        if isinstance(raw, str):
            return raw
    return ""


def _host_will_ask(command: str, asks: _Asks) -> bool:
    """True when the host will put ``command`` to a person. A failure answers no."""
    if not command:
        return False
    try:
        return bool(asks(command))
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class Allow:
    """The tool call proceeds. There is no model-facing text."""


@dataclass(frozen=True, slots=True)
class Block:
    """The tool call stops. ``message`` is what the model sees."""

    message: str


@dataclass(frozen=True, slots=True)
class Approve:
    """The host should ask before the tool call runs.

    ``message`` is what the model sees. ``rule_key`` names the approval rule.
    """

    message: str
    rule_key: str


Decision = Allow | Block | Approve


def blocks(severity: Severity) -> bool:
    """True when ``severity`` is high or critical.

    A value that is not a known severity does not block.
    """
    return at_least(severity, Severity.HIGH)


def worst(findings: Sequence[ScanFinding]) -> ScanFinding:
    """The most severe finding, breaking ties toward higher confidence.

    The caller passes a non-empty sequence. A finding whose severity is not
    known loses to every known severity.
    """
    return max(findings, key=lambda f: (severity_rank(f.severity), f.confidence))


def is_dangerous(tool_name: str, read_only: frozenset[str]) -> bool:
    """True when the canonical tool name is outside the read-only set."""
    return canonicalize_tool_name(tool_name) not in read_only


def is_ingestion(tool_name: str, non_ingesting: frozenset[str]) -> bool:
    """True when a non-empty canonical name is not excluded from result scanning."""
    canon = canonicalize_tool_name(tool_name)
    if not canon:
        return False  # named-tool floor; blank/missing/whitespace-only
    return canon not in non_ingesting


def is_egress_sink(tool_name: str, sinks: frozenset[str]) -> bool:
    """True when the canonical tool name is a member of ``sinks``."""
    return canonicalize_tool_name(tool_name) in sinks


def match_source_namespace(tool_name: str, namespaces: frozenset[str]) -> str | None:
    """Return the longest declared source-namespace prefix, or ``None``.

    The tool name is canonicalized the same way a sink is. A namespace labels a
    family, so the match is a prefix. The longest prefix wins.
    """
    canon_tool = canonicalize_tool_name(tool_name)
    return max(
        (prefix for prefix in namespaces if canon_tool.startswith(prefix)),
        key=len,
        default=None,
    )


def normalize_posture(raw: object) -> str:
    """``approve`` or ``block``. Anything else is block."""
    return raw if raw == "approve" else "block"


def approve_message(tool_name: str, rule_key: str, excerpt: str) -> str:
    """The model-facing text for one approval ask."""
    label = f"Command (from tool arguments): {excerpt}"
    if rule_key == "petasos.degraded":
        return (
            f"Petasos asks for approval before running '{tool_name}'. "
            f"Parameter scan is unreliable (petasos.degraded). {label}"
        )
    return f"Petasos asks for approval before running '{tool_name}'. Rule: {rule_key}. {label}"


def approve_decision(
    tool_name: str,
    session_id: str,
    rule_key: str,
    excerpt: str,
    *,
    logger: logging.Logger,
) -> Approve:
    """Ask the host to approve one call. Logs the ask on ``logger``."""
    logger.info("PETASOS_APPROVE tool=%s session=%s rule_key=%s", tool_name, session_id, rule_key)
    return Approve(approve_message(tool_name, rule_key, excerpt), rule_key)


def dangerous_tool_decision(
    tool_name: str,
    args: Any,
    session_id: str,
    result: GuardResult,
    egress: bool,
    posture: str,
    approve_available: bool,
    yolo: bool,
    *,
    namespaces: frozenset[str],
    taint_store: Any,
    always_approved: _Always,
    degraded_recorded: _Recorded,
    excerpt_for: _Excerpt,
    logger: logging.Logger,
    emit: _Emit,
    command_will_be_asked: _Asks = _not_asked,
) -> Block | Approve | None:
    """Decide a dangerous tool call after the guard has allowed it.

    ``None`` means the call proceeds. Taint, non-PII findings, PII leaving
    through an egress sink, a degraded parameter scan, and command-rule
    findings are considered in that order. ``always_approved`` and
    ``degraded_recorded`` are host facts. ``excerpt_for`` runs only when the
    decision is an approval.

    A terminal command-rule finding is recorded and not decided here when the
    posture is ``approve``, the host would not grant that approval with nobody
    attached, and ``command_will_be_asked`` says the host will ask a person
    about that command. Anything else is decided as before.
    """
    approve_effective = posture == "approve" and approve_available and not yolo
    blocking = [f for f in result.findings if blocks(f.severity)]
    non_pii = [f for f in blocking if f.finding_type != "pii"]
    pii = [f for f in blocking if f.finding_type == "pii"]
    command = [f for f in non_pii if str(f.rule_id).startswith(COMMAND_RULE_PREFIX)]
    other = [f for f in non_pii if not str(f.rule_id).startswith(COMMAND_RULE_PREFIX)]

    if egress and namespaces and taint_store is not None:
        tainted_ns = taint_store.tainted_source(session_id, args)
        if tainted_ns is not None:
            reason = f"source-taint egress: {tainted_ns} -> {tool_name}"
            logger.warning(
                "PETASOS_QUARANTINE tool=%s session=%s — %s", tool_name, session_id, reason
            )
            emit(
                session_id=session_id,
                tool=tool_name,
                event_type="quarantine",
                reason=reason,
            )
            return Block(format_content_block("taint_egress", tool_name, ()))

    if other:
        top = worst(other)
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — %s finding: %s",
            tool_name,
            session_id,
            top.severity.name,
            top.message,
        )
        emit(
            session_id=session_id,
            tool=tool_name,
            event_type="quarantine",
            severity=top.severity.name,
            rule_id=top.rule_id,
            reason=top.message,
        )
        return Block(format_content_block("non_pii_param", tool_name, tuple(other)))

    if pii and egress:
        top = worst(pii)
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — PII to egress sink: %s",
            tool_name,
            session_id,
            top.message,
        )
        emit(
            session_id=session_id,
            tool=tool_name,
            event_type="quarantine",
            severity=top.severity.name,
            rule_id=top.rule_id,
            reason=top.message,
        )
        return Block(format_content_block("pii_egress", tool_name, tuple(pii)))

    if result.param_scan_degraded:
        if always_approved("petasos.degraded"):
            pass
        elif not approve_effective:
            logger.warning(
                "PETASOS_QUARANTINE tool=%s session=%s — param scan degraded",
                tool_name,
                session_id,
            )
            emit(
                session_id=session_id,
                tool=tool_name,
                event_type="quarantine",
                param_scan_degraded=True,
                reason="param scan degraded",
            )
            return Block(format_content_block("degraded", tool_name, tuple(blocking)))
        elif degraded_recorded(session_id):
            pass
        else:
            return approve_decision(
                tool_name,
                session_id,
                "petasos.degraded",
                excerpt_for(),
                logger=logger,
            )

    remaining = [f for f in command if not always_approved(f.rule_id)]
    if remaining:
        top = worst(remaining)
        command_text = _command_text(args)
        if (
            posture == "approve"
            and not yolo
            and canonicalize_tool_name(tool_name) == "terminal"
            and _host_will_ask(command_text, command_will_be_asked)
        ):
            logger.info(
                "PETASOS_DEFER tool=%s session=%s rule_id=%s",
                tool_name,
                session_id,
                top.rule_id,
            )
            emit(
                session_id=session_id,
                tool=tool_name,
                event_type="deferred",
                severity=top.severity.name,
                rule_id=top.rule_id,
                reason=top.message,
            )
            return None
        if approve_effective:
            return approve_decision(
                tool_name,
                session_id,
                top.rule_id,
                excerpt_for(),
                logger=logger,
            )
        logger.warning(
            "PETASOS_QUARANTINE tool=%s session=%s — %s finding: %s",
            tool_name,
            session_id,
            top.severity.name,
            top.message,
        )
        emit(
            session_id=session_id,
            tool=tool_name,
            event_type="quarantine",
            severity=top.severity.name,
            rule_id=top.rule_id,
            reason=top.message,
        )
        return Block(format_content_block("non_pii_param", tool_name, tuple(remaining)))
    return None


def guard_denial(
    tool_name: str,
    session_id: str,
    result: GuardResult,
    *,
    logger: logging.Logger,
    emit: _Emit,
) -> Block | None:
    """Block a tier-3 or otherwise disallowed guard result.

    ``None`` when the guard allowed the call. Tier 3 is logged and emitted
    ahead of any other denial.
    """
    if result.tier == "tier3":
        logger.critical(
            "PETASOS_TIER3 tool=%s session=%s — all tool calls blocked", tool_name, session_id
        )
        emit(session_id=session_id, tool=tool_name, event_type="tier3", tier="tier3")
        return Block(format_block_message(result, tool_name))

    if not result.allowed:
        logger.warning(
            "PETASOS_BLOCK tool=%s session=%s reason=%s", tool_name, session_id, result.reason
        )
        emit(
            session_id=session_id,
            tool=tool_name,
            event_type="block",
            tier=result.tier,
            reason=result.reason,
        )
        return Block(format_block_message(result, tool_name))
    return None


def annotate_ingestion(
    tool_name: str,
    result_text: str,
    findings: Sequence[ScanFinding],
    *,
    cause: str | None,
    regime: _Regime | None,
    scanned_chars: int,
    total_chars: int,
    session_id: str,
    logger: logging.Logger,
    emit: _Emit,
) -> str | None:
    """Return an annotated tool result, or ``None`` when nothing is prefixed.

    A ``cause`` yields the unavailable banner and does not emit: the caller
    owns the cadence of that event. PII findings produce no banner. A clean
    scan that hit the length ceiling yields the ceiling banner.
    """
    if cause is not None:
        return format_result_notice("scan_unavailable", tool_name) + "\n\n" + result_text

    blocking = [finding for finding in findings if blocks(finding.severity)]
    non_pii = [finding for finding in blocking if finding.finding_type != "pii"]
    if non_pii:
        top = worst(non_pii)
        logger.warning(
            "PETASOS_INGEST_FLAGGED tool=%s session=%s rule=%s severity=%s",
            tool_name,
            session_id,
            top.rule_id,
            top.severity.name,
        )
        emit(
            session_id=session_id,
            tool=tool_name,
            event_type="ingest_flagged",
            severity=top.severity.name,
            rule_id=top.rule_id,
            reason=(
                f"{top.message} (tool result len={len(result_text)}, "
                f"coverage={regime}, scanned={scanned_chars})"
            ),
        )
        notice = format_result_notice(
            "findings",
            tool_name,
            top,
            len(non_pii),
            scanned_chars,
            total_chars,
            coverage=regime,
        )
        return notice + "\n\n" + result_text

    if regime == "ceiling":
        logger.info(
            "PETASOS_RESULT_CEILING tool=%s len=%d scanned=%d",
            tool_name,
            total_chars,
            scanned_chars,
        )
        notice = format_result_notice(
            "ceiling",
            tool_name,
            None,
            0,
            scanned_chars,
            total_chars,
            coverage="ceiling",
        )
        return notice + "\n\n" + result_text
    return None
