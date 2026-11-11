"""Tool results and the bookkeeping after a call finishes.

A result scan never withholds the text. A failure returns ``None``, which tells
the host to keep the original string. Taint is recorded only for a finished
call that has a stable session.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import TYPE_CHECKING, Any

from petasos.enforce.core import Core, Phase
from petasos.enforce.decisions import (
    RESULT_SCAN_ERROR_REASON,
    annotate_ingestion,
    is_ingestion,
    match_source_namespace,
)
from petasos.normalize import canonicalize_tool_name
from petasos.pipeline.ingest import scan_ingestion_result
from petasos.session.guard import NON_INGESTING_TOOLS

if TYPE_CHECKING:
    from petasos.enforce.types import ToolCall

logger = logging.getLogger("petasos.enforce")

_NON_INGESTING = frozenset(
    canon for canon in (canonicalize_tool_name(name) for name in NON_INGESTING_TOOLS) if canon
)
_DEFAULT_TIMEOUT = 10.0


def _ingestion(tool_name: str) -> bool:
    return is_ingestion(tool_name, _NON_INGESTING)


def _budget(core: Core) -> float:
    engine = core.engine
    raw = _DEFAULT_TIMEOUT
    if engine is not None:
        raw = float(engine.config.scanners.timeout_seconds)
    if raw <= 0:
        raw = _DEFAULT_TIMEOUT
    return min(60.0, raw) + core.limits.result_margin_s


def _skip(core: Core, tool: str, kind: str) -> None:
    canon = canonicalize_tool_name(tool)
    excluded = kind == "excluded" and canon in _NON_INGESTING
    if not core.book.note_ingest_skip(canon, kind, excluded):
        return
    if kind == "excluded":
        logger.debug("PETASOS_INGEST_EXCLUDED tool=%s canon=%s", tool, canon)
    else:
        logger.debug("PETASOS_INGEST_NOT_STRING tool=%s kind=%s", tool, kind)


def _cadence_key(call: ToolCall, session_id: str) -> str:
    host = call.host_session
    if isinstance(host, str) and host.strip():
        return host
    if call.session.strip():
        return call.session
    if call.agent is not None and session_id.strip():
        return session_id
    return "uncorrelated"


async def _ingest(
    core: Core,
    pipeline: Any,
    text: str,
    session_id: str | None,
    armed: bool,
    guard: Any,
    budget: float,
) -> Any:
    lock = core.runtime.ingest_lock
    if lock is None:
        lock = asyncio.Lock()
    async with lock:
        return await asyncio.wait_for(
            scan_ingestion_result(
                pipeline,
                text,
                direction="inbound",
                session_id=session_id if armed else None,
                weight_cap=guard.scan_weight_cap if armed and guard is not None else 0.0,
                inspect_lock=core.runtime.inspect,
            ),
            timeout=budget,
        )


def transform(core: Core, call: ToolCall, result: object) -> str | None:
    """Annotate an ingested result, or return ``None`` to leave it unchanged."""
    core.observe(announce=False)
    if not core.armed:
        return None
    if not isinstance(result, str) or not result:
        if _ingestion(call.tool):
            kind = "empty" if isinstance(result, str) else type(result).__name__
            _skip(core, call.tool, kind)
        return None
    if not _ingestion(call.tool):
        canon = canonicalize_tool_name(call.tool)
        if not canon:
            return None
        _skip(core, call.tool, "excluded")
        return None
    if core.phase is not Phase.READY or core.engine is None:
        return None

    session_id = core.book.session_id(call.session, call.agent)
    budget = _budget(core)
    engine = core.engine
    pipeline = engine.pipeline
    guard = engine.guard
    correlatable = bool(call.session) or call.agent is not None
    armed = guard is not None and correlatable
    scan = None
    cause: str | None = None
    uncorrelated = "no_guard" if guard is None else "uncorrelatable"
    if not armed and core.book.claim_uncorrelated(uncorrelated):
        logger.warning(
            "PETASOS_INGEST_UNCORRELATED tool=%s cause=%s "
            "-- ingestion scans will not accumulate; session backstop inert",
            call.tool,
            uncorrelated,
        )
    try:
        scan = core.runtime.run_ingest(
            _ingest(core, pipeline, result, session_id, armed, guard, budget)
        )
    except (TimeoutError, concurrent.futures.TimeoutError):
        cause = "timeout"
    except Exception:
        cause = "raised"

    head = getattr(scan, "head", None) if scan is not None else None
    floor = None
    if head is not None:
        floor = next(
            (item for item in head.scanner_results if item.scanner_name == "minimal"),
            None,
        )
    findings = () if scan is None else scan.findings
    if cause is None:
        if scan is not None and getattr(scan, "inspect_failed", False):
            cause = "inspect_error"
        elif scan is None or head is None or not head.scanner_results or floor is None:
            cause = "boundary"
        elif floor.error is not None:
            cause = "floor_error"
        elif scan.errors:
            cause = "sweep_error"

    if cause is not None:
        try:
            if core.book.ingest_unscanned.due(_cadence_key(call, session_id)):
                logger.warning(
                    "PETASOS_INGEST_UNSCANNED tool=%s session=%s cause=%s len=%d",
                    call.tool,
                    session_id,
                    cause,
                    len(result),
                )
                core.emit(
                    session_id=session_id,
                    tool=call.tool,
                    event_type="ingest_unscanned",
                    reason=f"{RESULT_SCAN_ERROR_REASON} cause={cause} len={len(result)}",
                )
        except Exception:
            logger.warning(
                "PETASOS_INGEST_UNSCANNED_CADENCE_ERROR tool=%s cause=%s",
                call.tool,
                cause,
            )
        return annotate_ingestion(
            call.tool,
            result,
            findings,
            cause=cause,
            regime=None,
            scanned_chars=0,
            total_chars=0,
            session_id=session_id,
            logger=logger,
            emit=core.emit,
        )

    if scan is None:
        return None
    coverage = scan.coverage
    return annotate_ingestion(
        call.tool,
        result,
        findings,
        cause=None,
        regime=coverage.regime,
        scanned_chars=coverage.scanned_chars,
        total_chars=coverage.total_chars,
        session_id=session_id,
        logger=logger,
        emit=core.emit,
    )


def finished(core: Core, call: ToolCall, result: str, duration_ms: int) -> None:
    """Record taint for a completed call. A missing pipeline does nothing."""
    if core.phase is not Phase.READY or core.engine is None:
        return
    core.observe(announce=False)
    if not core.armed:
        return
    logger.debug("PETASOS_TOOL_COMPLETE tool=%s duration_ms=%d", call.tool, duration_ms)
    engine = core.engine
    if engine is None or not engine.namespaces:
        return
    try:
        source = match_source_namespace(call.tool, engine.namespaces)
        if source is None:
            return
        if not call.session and call.agent is None:
            return
        engine.taint.capture(
            core.book.session_id(call.session, call.agent),
            result,
            source,
        )
    except Exception as exc:
        logger.debug("Petasos taint capture failed: %s; skipping", exc)
