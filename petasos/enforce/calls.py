"""The tool-call decision.

Disarmed calls are counted and not scanned. A call that arrives before the
pipeline is ready, or after initialisation has failed, goes through the
syntactic fallback. A clean scan that finishes as the pipeline becomes ready
falls through to the guard. The guard's own failure uses the same fallback,
except a terminated session, which is a tier-3 block.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import logging
import math
from typing import TYPE_CHECKING, Any, cast

from petasos.enforce.approvals import command_excerpt, degraded_pending_key
from petasos.enforce.core import Core, Phase
from petasos.enforce.decisions import (
    Allow,
    Approve,
    Block,
    Decision,
    dangerous_tool_decision,
    guard_denial,
    is_dangerous,
    is_egress_sink,
)
from petasos.enforce.fallback import fallback_decision, scan_fallback, tier3_unavailable_block
from petasos.enforce.guardrail import hit_for, note_blocked, note_covered, ruling_for
from petasos.guard.guardrail import CheckFailure, unavailable_message
from petasos.guard.tools import READ_ONLY_TOOLS
from petasos.normalize import canonicalize_tool_name
from petasos.pipeline.ingest import _acquire_inspect_lock

if TYPE_CHECKING:
    from petasos.enforce.types import ToolCall
    from petasos.guard.guard import GuardResult

logger = logging.getLogger("petasos.enforce")

_READ_ONLY = frozenset(
    canon for canon in (canonicalize_tool_name(name) for name in READ_ONLY_TOOLS) if canon
)
_COLD_REASON = (
    "scanners not up; tool results unscanned; syntactic only,"
    " dangerous tools only, params only (100k cap)"
)
_COLD_REASON_NO_INIT = (
    "scanners not up (no init in flight); tool results unscanned;"
    " syntactic only, dangerous tools only, params only (100k cap)"
)
_FAILED_PREFIX = (
    "scanner init failed; syntactic fallback only (dangerous tools, params, 100k cap);"
    " tool results unscanned; no ML scanners: "
)
_COLD_BLOCK = "cold-window block: scanners not up, no finding; blocked by fail-mode policy"
_FAILED_BLOCK = (
    "init-failed block: scanners permanently unavailable, no finding; blocked by fail-mode policy"
)
_EVAL_TIMEOUT = "evaluation_timeout"
_EVAL_ERROR = "evaluation_error"
_EVAL_TIMEOUT_REASON = "guard evaluation unavailable: evaluation_timeout"
_EVAL_ERROR_REASON = "guard evaluation unavailable: evaluation_error"
_MAX_INIT_ERROR = 60


def _dangerous(tool_name: str) -> bool:
    return is_dangerous(tool_name, _READ_ONLY)


def _latch_key(call: ToolCall, session_id: str) -> str | None:
    if not call.session and call.agent is None:
        return None
    return session_id


def _marker(
    core: Core,
    *,
    latch: str | None,
    session_id: str,
    tool: str,
    event_type: str,
    reason: str,
) -> None:
    if not core.book.claim_cold(latch, event_type):
        return
    wrote = core.emit(
        session_id=session_id,
        tool=tool,
        event_type=event_type,
        param_scan_degraded=True,
        reason=reason,
    )
    if wrote:
        return
    core.book.release_cold(latch, event_type)
    if core.book.cold_fail.due():
        logger.warning(
            "PETASOS_COLD_START_UNRECORDED type=%s session=%s: enforcement spool write failed; %s",
            event_type,
            session_id,
            reason,
        )


def _scan(core: Core, call: ToolCall) -> tuple[Block | None, str | None]:
    def run(coro: Any) -> Any:
        return core.run(coro)

    try:
        scanned = scan_fallback(
            call.tool,
            call.args,
            is_dangerous=_dangerous,
            session_id_for=lambda: core.book.session_id(call.session, call.agent),
            scanner_for=core.fallback_scanner,
            run=run,
            logger=logger,
            emit=core.emit,
        )
    except Exception as exc:
        logger.warning("PETASOS_FALLBACK_DISPATCH_FAILED tool=%r — %s", call.tool, exc)
        return None, None
    return scanned.block, scanned.outcome


def _fallback(
    core: Core,
    call: ToolCall,
    outcome: str | None,
    *,
    session_id: str,
    log_cause: str,
    block_reason: str,
) -> Block | None:
    return fallback_decision(
        call.tool,
        outcome,
        session_id=session_id,
        log_cause=log_cause,
        block_reason=block_reason,
        fail_mode=core.fail_mode,
        is_dangerous=_dangerous,
        logger=logger,
        emit=core.emit,
    )


async def _evaluate(core: Core, call: ToolCall, session_id: str) -> Any:
    kind, _timeout = core.fault.current()
    if kind == "error":
        raise RuntimeError("guard evaluation failed")
    if kind == "timeout":
        await asyncio.Event().wait()
    acquired = False
    try:
        await _acquire_inspect_lock(core.runtime.inspect)
        acquired = True
        engine = core.engine
        if engine is None:
            raise RuntimeError("pipeline is not ready")
        args = dict(call.args)
        return await engine.guard.evaluate(call.tool, args, session_id)
    finally:
        if acquired:
            core.runtime.inspect.release()


def _terminated(core: Core, session_id: str) -> bool:
    engine = core.engine
    tracker = None if engine is None else engine.tracker
    if tracker is None:
        logger.error(
            "terminated-floor check failed for session=%s — returning tier3 fail-secure",
            session_id,
        )
        return True
    try:
        if tracker.is_terminated(session_id):
            return True
        lineage = engine.lineage if engine is not None else None
        if lineage is not None:
            for ancestor in lineage.ancestors(session_id):
                if tracker.is_terminated(ancestor):
                    return True
        return False
    except Exception:
        logger.exception(
            "terminated-floor check failed for session=%s — returning tier3 fail-secure",
            session_id,
        )
        return True


def _note_eval(
    core: Core, call: ToolCall, session_id: str, exc: BaseException, cause: str
) -> None:
    key: str | None = None if (not call.session and call.agent is None) else session_id
    message = "Petasos guard evaluation failed: %s — guard evaluation unavailable: %s"
    if core.book.note_eval(key):
        logger.error(message, exc, cause)
    else:
        logger.debug(message, exc, cause)


def _approve_excerpt(core: Core, call: ToolCall, result: object) -> str:
    def load() -> Any:
        redact = core.host.redactor
        if redact is None:
            raise RuntimeError("redactor unavailable")
        return redact

    return command_excerpt(call.args, result, load_redactor=load)


def _posture(core: Core) -> str:
    engine = core.engine
    if engine is None:
        return "block"
    try:
        raw = engine.config.tools.dangerous_posture
    except Exception:
        return "block"
    return raw if raw == "approve" else "block"


def _grant_unattended(core: Core) -> bool:
    # Only an explicit False is a person attached. Any other answer is not.
    try:
        return core.host.approval_grant().unattended is not False
    except Exception:
        return True


def _always(core: Core, rule_key: str) -> bool:
    try:
        return bool(core.host.rule_always_approved(rule_key))
    except Exception:
        return False


def decide(core: Core, call: ToolCall) -> Decision:
    """Decide one tool call. Raises only on a programming error the caller wraps."""
    core.observe(announce=False)
    if not core.armed:
        session_id = core.book.session_id(call.session, call.agent)
        count = core.book.bump_bypass(session_id)
        if core.book.disarm.due():
            logger.warning(
                "PETASOS_DISARMED tool=%s — enforcement bypassed by operator (Unequipped)",
                call.tool,
            )
            core.emit(
                session_id=session_id,
                tool=call.tool,
                event_type="bypassed_disarmed",
                armed=False,
                bypassed_count=count,
            )
        return Allow()

    ready = core.ensure()
    session_id = core.book.session_id(call.session, call.agent)
    if not ready:
        latch = _latch_key(call, session_id)
        if core.phase is Phase.FAILED or core.init_error is not None:
            logger.debug("Petasos init failed — running syntactic fallback")
            detail = (core.init_error or "")[:_MAX_INIT_ERROR]
            _marker(
                core,
                latch=latch,
                session_id=session_id,
                tool=call.tool,
                event_type="init_failed",
                reason=_FAILED_PREFIX + detail,
            )
            block, outcome = _scan(core, call)
            return _guardrail_or_fallback(
                core,
                call,
                session_id,
                block
                or _fallback(
                    core,
                    call,
                    outcome,
                    session_id=session_id,
                    log_cause="init failed",
                    block_reason=_FAILED_BLOCK,
                ),
            )
        if core.phase is not Phase.READY:
            reason = _COLD_REASON if core._started else _COLD_REASON_NO_INIT
            _marker(
                core,
                latch=latch,
                session_id=session_id,
                tool=call.tool,
                event_type="cold_start_degraded",
                reason=reason,
            )
        block, outcome = _scan(core, call)
        if block is not None or outcome != "clean" or core.phase is not Phase.READY:
            return _guardrail_or_fallback(
                core,
                call,
                session_id,
                block
                or _fallback(
                    core,
                    call,
                    outcome,
                    session_id=session_id,
                    log_cause="cold window",
                    block_reason=_COLD_BLOCK,
                ),
            )

    core.observe(announce=True)
    session_id = core.book.session_id(call.session, call.agent)
    kind, fault_timeout = core.fault.current()
    timeout = fault_timeout if kind == "timeout" and fault_timeout is not None else None
    try:
        result = core.run(_evaluate(core, call, session_id), timeout)
    except Exception as exc:
        if isinstance(exc, concurrent.futures.TimeoutError):
            cause = _EVAL_TIMEOUT
            reason = _EVAL_TIMEOUT_REASON
        else:
            cause = _EVAL_ERROR
            reason = _EVAL_ERROR_REASON
        _note_eval(core, call, session_id, exc, cause)
        if _terminated(core, session_id):
            return tier3_unavailable_block(call.tool, session_id, logger=logger, emit=core.emit)
        return _guardrail_or_fallback(
            core,
            call,
            session_id,
            _fallback(
                core,
                call,
                "errored",
                session_id=session_id,
                log_cause=reason,
                block_reason=reason,
            ),
        )

    target = getattr(result, "selfmod_target", None)
    if target is not None:
        try:
            finding = getattr(result, "selfmod_finding", None)
            core.emit(
                session_id=session_id,
                tool=call.tool,
                event_type="selfmod_attempt",
                rule_id=getattr(finding, "rule_id", None),
                severity=getattr(getattr(finding, "severity", None), "value", None),
                reason=f"selfmod target: {core.host.display_path(str(target))}",
            )
        except Exception:
            pass

    denied = guard_denial(call.tool, session_id, result, logger=logger, emit=core.emit)
    decision = denied or _dangerous_or_allow(core, call, session_id, result)
    kind = getattr(result, "guardrail_kind", None)
    if isinstance(kind, str) and kind:
        target = str(getattr(result, "selfmod_target", "") or "")
        if isinstance(decision, Block):
            note_blocked(core, call, session_id, kind=kind, target=target)
            return decision
        ruling = ruling_for(
            core,
            call,
            session_id,
            kind=kind,
            target=target,
        )
        if isinstance(ruling.decision, Approve) and isinstance(decision, Approve):
            return Approve(
                ruling.decision.message + "\n" + decision.message, ruling.decision.rule_key
            )
        if ruling.decision is not None:
            return ruling.decision
        note_covered(core, call, session_id, ruling)
        return decision
    return decision


def _dangerous_or_allow(core: Core, call: ToolCall, session_id: str, result: object) -> Decision:
    if not _dangerous(call.tool):
        return Allow()
    engine = core.engine
    namespaces = engine.namespaces if engine is not None else frozenset()
    taint = engine.taint if engine is not None else None
    sink = False if engine is None else is_egress_sink(call.tool, engine.egress)
    score: float | None = None
    tier: str | None = None
    if engine is not None:
        try:
            session = (
                engine.tracker.mint_token(session_id, engine.pipeline.host_id)
                if engine.secrets.session_secret is not None
                else session_id
            )
            state = engine.tracker.get_state(session)
            exact = state.last_score if state is not None else 0.0
            if math.isfinite(exact):
                score = round(exact, 1)
                tier = engine.guard.session_tier(session_id, include_rolling=True)
        except Exception:
            logger.exception("Could not read conversation risk for command judgment")
    decision = dangerous_tool_decision(
        call.tool,
        dict(call.args),
        session_id,
        cast("GuardResult", result),
        sink,
        _posture(core),
        core.host.approve_directive,
        _grant_unattended(core),
        namespaces=namespaces,
        taint_store=taint,
        always_approved=lambda rule: _always(core, rule),
        degraded_recorded=core.book.degraded_recorded,
        excerpt_for=lambda: _approve_excerpt(core, call, result),
        logger=logger,
        emit=core.emit,
        command_judge=core.host.command_judge,
        command_checker=core.host.command_checker,
        command_prompt_name=core.host.command_prompt_name,
        command_guardian_name=core.host.command_guardian_name,
        score=score,
        tier=tier,
    )
    if isinstance(decision, Approve) and decision.rule_key == "petasos.degraded":
        core.book.note_degraded_pending(
            session_id,
            degraded_pending_key(call.host_session, call.turn_id, call.tool_call_id),
        )
    if decision is None:
        return Allow()
    return decision


def _guardrail_or_fallback(
    core: Core,
    call: ToolCall,
    session_id: str,
    fallback: Block | None,
) -> Decision:
    """A fallback block wins. A recognised change is still not allowed through."""
    hit = hit_for(core, call, session_id)
    if isinstance(hit, CheckFailure):
        if core.fail_mode != "open":
            return Block(unavailable_message(call.tool))
        return fallback or Allow()
    if hit is None:
        return fallback or Allow()
    with contextlib.suppress(Exception):
        core.emit(
            session_id=session_id,
            tool=call.tool,
            event_type="selfmod_attempt",
            rule_id="petasos.selfmod.config_write",
            severity="critical",
            reason=f"selfmod target: {core.host.display_path(hit.target)}",
        )
    if fallback is not None:
        note_blocked(core, call, session_id, kind=hit.kind, target=hit.target)
        return fallback
    ruling = ruling_for(core, call, session_id, kind=hit.kind, target=hit.target)
    if ruling.decision is not None:
        return ruling.decision
    note_covered(core, call, session_id, ruling)
    return Allow()
