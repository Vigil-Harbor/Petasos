"""The host-facing enforcement object.

One ``Enforcer`` owns its pipeline, its loops, and its counters. Two
enforcers in one process do not share them. Construct it, call ``start``,
and pass each host hook to the matching method.

Threading. ``start`` returns before initialisation finishes. ``tool_call``,
``tool_result``, ``tool_finished``, ``session_started``, ``subagent_started``,
``subagent_stopped``, ``approval_requested``, ``approval_answered``,
``refresh``, ``status``, and ``session_tier`` may run at the same time, on
the threads the host uses for hooks. They serialise pipeline access on the
enforcer's loops. ``close`` is idempotent and may run alongside them; after
it returns, further calls do not scan.

A host-facing method does not raise. A failure becomes a decision under the
configured fail mode, or leaves a result unchanged, and is logged.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from petasos.enforce.calls import decide
from petasos.enforce.core import Core
from petasos.enforce.decisions import Allow, Block, Decision
from petasos.enforce.messages import format_content_block
from petasos.enforce.observe import (
    approval_answered,
    approval_requested,
    session_started,
    subagent_started,
    subagent_stopped,
    tier_of,
)
from petasos.enforce.results import finished, transform
from petasos.enforce.types import (
    ApprovalNotice,
    Clock,
    EvaluationFault,
    EventSink,
    HostInfo,
    InitGate,
    Limits,
    SettingsSource,
    Status,
    ToolCall,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from petasos.model import Scanner
    from petasos.scanners.registry import ScannerSpec

logger = logging.getLogger("petasos.enforce")


class Enforcer:
    """Stateful enforcement for one host process.

    ``source`` returns the current settings snapshot. ``host`` says what that
    host can do. ``events`` receives enforcement events; omit it and pass
    ``spool_path`` to use a signed spool at that path. ``clock`` supplies
    monotonic time for deadlines and log windows. ``scanners`` are added
    after the registry's own scanners. ``registry`` defaults to the built-in
    registry. ``limits`` are this object's deadlines. ``init`` holds or fails
    background initialisation. ``evaluation`` replaces the guard when a test
    needs the failure arms.

    ``start`` is non-blocking. ``close`` stops the background threads.
    """

    def __init__(
        self,
        source: SettingsSource,
        *,
        host: HostInfo | None = None,
        events: EventSink | None = None,
        clock: Clock | None = None,
        scanners: Sequence[Scanner] = (),
        registry: tuple[ScannerSpec, ...] | None = None,
        limits: Limits | None = None,
        init: InitGate | None = None,
        evaluation: EvaluationFault | None = None,
        spool_path: str | None = None,
    ) -> None:
        self._core = Core(
            source,
            host=host if host is not None else HostInfo(),
            events=events,
            clock=clock,
            scanners=scanners,
            registry=registry,
            limits=limits,
            init=init,
            evaluation=evaluation,
            spool_path=spool_path,
        )

    def start(self) -> None:
        """Begin background initialisation and return without waiting."""
        try:
            self._core.start()
        except Exception:
            logger.exception("Petasos start failed")

    def settle(self, timeout: float = 30.0) -> bool:
        """Wait until initialisation has finished or ``timeout`` elapses.

        Returns whether it finished. The tool-call path has its own shorter
        wait; this is for a host that wants the pipeline before the first call.
        """
        try:
            return self._core.settle(timeout)
        except Exception:
            logger.exception("Petasos settle failed")
            return False

    def tool_call(self, call: ToolCall) -> Decision:
        """Decide a tool call that is about to run. Never raises."""
        if self._core._closed:
            return Allow()
        try:
            return decide(self._core, call)
        except Exception as exc:
            logger.error("Petasos tool_call failed: %s", exc, exc_info=True)
            return self._failed_call(call)

    def tool_result(self, call: ToolCall, result: object) -> str | None:
        """Annotate a tool result, or return ``None`` to leave it unchanged.

        Never raises. ``None`` is also the answer when the scan itself fails,
        because the host keeps the original string in that case.
        """
        if self._core._closed:
            return None
        try:
            return transform(self._core, call, result)
        except Exception as exc:
            logger.warning(
                "PETASOS_RESULT_SCAN_ERROR tool=%s: %r; content passed through untouched",
                call.tool,
                exc,
            )
            return None

    def tool_finished(self, call: ToolCall, result: str = "", *, duration_ms: int = 0) -> None:
        """Record bookkeeping for a call that has finished. Never raises."""
        if self._core._closed:
            return
        try:
            finished(self._core, call, result, duration_ms)
        except Exception as exc:
            logger.debug("Petasos tool_finished failed: %s", exc)

    def session_started(self, session_id: str = "") -> None:
        """Note a session start. Never raises."""
        try:
            session_started(self._core, session_id)
        except Exception:
            logger.debug("Petasos session_started failed")

    def subagent_started(self, child: str, parent: str) -> None:
        """Record a sub-agent edge. Never raises."""
        try:
            subagent_started(self._core, child, parent)
        except Exception:
            logger.debug("Petasos subagent_started failed")

    def subagent_stopped(self, child: str) -> None:
        """Drop a sub-agent edge. Never raises."""
        try:
            subagent_stopped(self._core, child)
        except Exception:
            logger.debug("Petasos subagent_stopped failed")

    def approval_requested(self, notice: ApprovalNotice) -> None:
        """Record an approval request. Never raises."""
        try:
            approval_requested(self._core, notice)
        except Exception:
            logger.debug("PETASOS_APPROVAL emit failed")

    def approval_answered(self, notice: ApprovalNotice) -> None:
        """Record an approval answer. Never raises."""
        try:
            approval_answered(self._core, notice)
        except Exception:
            logger.debug("PETASOS_APPROVAL emit failed")

    def refresh(self) -> None:
        """Apply the current snapshot now, without the live-change log line.

        A host calls this when it has switched settings for a reason it logs
        itself, such as a profile change. A later tool call does not log that
        same change again. Restart-only changes are still reported.
        """
        if self._core._closed:
            return
        try:
            self._core.observe(announce=False)
            snap = self._core._pending
            engine = self._core.engine
            if snap is None or snap.config is None or snap.error or engine is None:
                return
            if snap.token == self._core._token:
                return
            from petasos.enforce.engine import apply_snapshot
            from petasos.enforce.guardrail import record_applied_settings

            before = engine.config
            apply_snapshot(engine, snap.config, snap.secrets, logger)
            record_applied_settings(self._core, before)
            self._core._token = snap.token
            self._core.fail_mode = engine.fail_mode()
            self._core._install_secret(engine.secrets)
        except Exception as exc:
            self._core.book.log_reload_failure(f"apply failed: {exc}")

    def status(self) -> Status:
        """The lifecycle. Never raises; a failure is reported as ``failed``."""
        try:
            return self._core.status()
        except Exception as exc:
            logger.error("Petasos status failed: %s", exc)
            return Status("failed", True, str(exc) or type(exc).__name__)

    def session_tier(self, session_id: str) -> str | None:
        """The tier enforcement is using for ``session_id``, or ``None``."""
        try:
            return tier_of(self._core, session_id)
        except Exception:
            return None

    def close(self) -> None:
        """Stop background threads. Idempotent. Never raises."""
        try:
            self._core.close()
        except Exception:
            logger.exception("Petasos close failed")

    def _failed_call(self, call: ToolCall) -> Decision:
        if self._core.fail_mode == "open":
            return Allow()
        with contextlib.suppress(Exception):
            self._core.emit(
                session_id=call.session,
                tool=call.tool,
                event_type="quarantine",
                param_scan_degraded=True,
                reason="enforcer internal error",
            )
        return Block(format_content_block("degraded", call.tool or "tool", ()))
