"""Session, sub-agent, and approval observation.

These do not decide a tool call. A missing pipeline makes the sub-agent
hooks a no-op, which is what happens before initialisation finishes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from petasos._limits import MAX_PARAM_TEXT_LEN
from petasos.enforce.approvals import (
    approval_event,
    degraded_choice_confirmed,
    degraded_pending_key,
    is_degraded_pattern,
    redact_display_text,
    redaction_status,
)
from petasos.enforce.core import Core, Phase

if TYPE_CHECKING:
    from petasos.enforce.types import ApprovalNotice

logger = logging.getLogger("petasos.enforce")

_FIELD_MAX = 200
_DESCRIPTION_MAX = 400


def session_started(core: Core, session_id: str) -> None:
    """Note that a session started. The id is the host's; the line is fixed."""
    del core, session_id
    logger.info("PETASOS_SESSION_START — Petasos content security active")


def subagent_started(core: Core, child: str, parent: str) -> None:
    """Record that ``parent`` spawned ``child``. Ignored until lineage exists."""
    engine = core.engine
    if engine is None or engine.lineage is None:
        return
    if not child or not parent:
        logger.debug("subagent_start missing parent/child id — ignoring edge")
        return
    engine.lineage.register(child, parent)


def subagent_stopped(core: Core, child: str) -> None:
    """Drop ``child``'s lineage edge. Idempotent."""
    engine = core.engine
    if engine is None or engine.lineage is None or not child:
        return
    engine.lineage.unregister(child)


def _fields(notice: ApprovalNotice) -> dict[str, object]:
    return {
        "coalesced": notice.coalesced,
        "command": notice.command,
        "decided_by": notice.decided_by,
        "description": notice.description,
        "pattern_key": notice.pattern_key,
        "pattern_keys": list(notice.pattern_keys),
        "session_id": notice.session_id,
        "session_key": notice.session_key,
        "surface": notice.surface,
        "tool_call_id": notice.tool_call_id,
        "turn_id": notice.turn_id,
    }


def _emit(core: Core, phase: str, notice: ApprovalNotice, choice: object) -> None:
    command, command_status = redact_display_text(
        notice.command, _FIELD_MAX, redact=core.host.redactor, max_len=MAX_PARAM_TEXT_LEN
    )
    description, description_status = redact_display_text(
        notice.description,
        _DESCRIPTION_MAX,
        redact=core.host.redactor,
        max_len=MAX_PARAM_TEXT_LEN,
    )
    redaction = redaction_status({command_status, description_status})
    event = approval_event(
        phase,
        choice=choice,
        armed=core.armed,
        command=command,
        description=description,
        redaction=redaction,
        fields=_fields(notice),
    )
    wrote = False
    sink = core._sink
    if sink is not None:
        wrote = bool(sink.emit(event))
    if not wrote:
        logger.debug("PETASOS_APPROVAL emit failed phase=%s", phase)
        return
    stored = event["choice"]
    logger.info(
        "PETASOS_APPROVAL phase=%s choice=%s tool=%s session_id=%s rule_id=%s surface=%s",
        phase,
        "" if stored is None else stored,
        event["tool"],
        event["session_id"],
        event["rule_id"],
        event["surface"],
    )


def approval_requested(core: Core, notice: ApprovalNotice) -> None:
    """Record an approval request. The choice is always empty."""
    core.observe(announce=False)
    _emit(core, "request", notice, None)


def approval_answered(core: Core, notice: ApprovalNotice) -> None:
    """Record an answer, and a confirmed degraded approve for that session."""
    core.observe(announce=False)
    try:
        if is_degraded_pattern(notice.pattern_key):
            core.book.apply_degraded(
                degraded_pending_key(notice.session_id, notice.turn_id, notice.tool_call_id),
                degraded_choice_confirmed(notice.choice),
            )
    except Exception as exc:
        logger.debug("PETASOS_DEGRADED_PENDING apply failed error=%r", exc)
    _emit(core, "response", notice, notice.choice)


def tier_of(core: Core, session_id: str) -> str | None:
    """The session tier, or ``None`` when the guard does not exist yet."""
    engine = core.engine
    if engine is None or core.phase is not Phase.READY:
        return None
    try:
        tier = engine.guard.session_tier(session_id)
    except Exception:
        return None
    if not isinstance(tier, str):
        return None
    return tier
