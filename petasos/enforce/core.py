"""Lifecycle and settings for one enforcer.

The phase is ``starting``, ``ready``, or ``failed``. The armed switch is
applied on top when a caller asks for status. Initialisation reads the
settings source, then waits on the gate if a test held it, then builds the
pipeline. A call that arrives early uses the fail mode from the latest
readable snapshot.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum
from typing import TYPE_CHECKING, Any

from petasos.config.sections import PetasosConfig
from petasos.enforce.approvals import redact_display_text
from petasos.enforce.book import Book
from petasos.enforce.engine import Engine, apply_snapshot, build_engine, syntactic_scanner
from petasos.enforce.events import EventSpool
from petasos.enforce.guardrail import Grants, record_applied_settings
from petasos.enforce.runtime import AsyncBridge
from petasos.enforce.types import (
    Clock,
    EvaluationFault,
    EventSink,
    HostInfo,
    InitGate,
    Limits,
    SettingsSnapshot,
    SettingsSource,
    Status,
    SystemClock,
)
from petasos.guard.guardrail import CheckFailures
from petasos.limits import MAX_PARAM_TEXT_LEN
from petasos.scanners.registry import REGISTRY, ScannerSpec

if TYPE_CHECKING:
    from collections.abc import Sequence

    from petasos.model import Scanner

logger = logging.getLogger("petasos.enforce")

_UNSET = object()
_DEFAULT_FAIL = "degraded"


class Phase(Enum):
    """Initialisation, without the armed switch."""

    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


class _DropSink:
    """A sink that accepts events and stores nothing."""

    def emit(self, event: object) -> bool:
        del event
        return False


class Core:
    """The mutable state of one enforcer. Not safe to construct twice for one host."""

    def __init__(
        self,
        source: SettingsSource,
        *,
        host: HostInfo,
        events: EventSink | None,
        clock: Clock | None,
        scanners: Sequence[Scanner],
        registry: tuple[ScannerSpec, ...] | None,
        limits: Limits | None,
        init: InitGate | None,
        evaluation: EvaluationFault | None,
        spool_path: str | None,
    ) -> None:
        self.source = source
        self.host = host
        self.clock = clock if clock is not None else SystemClock()
        self.limits = limits if limits is not None else Limits()
        self.scanners = tuple(scanners)
        self.registry = registry if registry is not None else REGISTRY
        self.gate = init
        self.fault = evaluation if evaluation is not None else EvaluationFault()
        self.runtime = AsyncBridge()
        self.book = Book(self.clock, self.limits.log_every_s, logger)
        self.grants = Grants()
        self.check_failures = CheckFailures()
        self.phase = Phase.STARTING
        self.init_error: str | None = None
        self.engine: Engine | None = None
        self.armed = True
        self.fail_mode = _DEFAULT_FAIL
        self._token: object = _UNSET
        self._pending: SettingsSnapshot | None = None
        self._secret_invalid = False
        self._init_done = threading.Event()
        self._init_lock = threading.Lock()
        self._deadline: float | None = None
        self._wait_expired = False
        self._started = False
        self._building = False
        self._closed = False
        self._thread: threading.Thread | None = None
        self._fallback: Scanner | None = None
        self._fallback_lock = threading.Lock()
        self._sink = events
        self._spool: EventSpool | None = None
        self._spool_path = spool_path
        if events is None and spool_path is not None:
            self._spool = EventSpool(spool_path)
            self._sink = self._spool

    def start(self) -> None:
        """Begin initialisation on a background thread and return."""
        with self._init_lock:
            if self._started or self._closed:
                return
            self._started = True
            self.phase = Phase.STARTING
            self._observe(announce=False)
            self._thread = threading.Thread(
                target=self._initialise, name="petasos-init", daemon=True
            )
            self._thread.start()

    def settle(self, timeout: float) -> bool:
        """Wait until initialisation has left ``starting``. True when it has."""
        return self._init_done.wait(timeout)

    def close(self) -> None:
        """Stop the loops and unblock initialisation. A second call does nothing."""
        with self._init_lock:
            if self._closed:
                return
            self._closed = True
        if self.gate is not None:
            self.gate.fail("closed")
        self._init_done.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self.runtime.close()

    def status(self) -> Status:
        """The lifecycle a caller should display."""
        self._observe(announce=False)
        if self._closed:
            return Status("failed", self.armed, "closed")
        if not self.armed:
            return Status("disarmed", False, None)
        if self.phase is Phase.READY:
            return Status("ready", True, None)
        if self.phase is Phase.FAILED:
            return Status("failed", True, self.init_error)
        return Status("starting", True, None)

    def ensure(self) -> bool:
        """True when the pipeline is live. Waits at most one cold-start budget."""
        if self.phase is Phase.READY and self.engine is not None:
            return True
        if self.phase is Phase.FAILED:
            return False
        if not self._started:
            self._initialise()
            return self.phase is Phase.READY and self.engine is not None
        if self.gate is not None and self.gate.skip_wait:
            return False
        if self._wait_expired:
            return False
        now = self.clock.monotonic()
        with self._init_lock:
            deadline = self._deadline
            if deadline is None:
                deadline = now + self._budget()
                self._deadline = deadline
        remaining = deadline - now
        if remaining > 0:
            self._init_done.wait(remaining)
        if self.phase is Phase.STARTING:
            self._wait_expired = True
        return self.phase is Phase.READY and self.engine is not None

    def observe(self, *, announce: bool) -> None:
        """Re-read settings. ``announce`` logs a live change after the pipeline exists."""
        self._observe(announce=announce)

    def emit(self, **kwargs: Any) -> bool:
        """Write one enforcement event. Never raises."""
        try:
            reason = kwargs.get("reason", "")
            if not isinstance(reason, str):
                reason = str(reason)
            safe, status = redact_display_text(
                reason, 200, redact=self.host.redactor, max_len=MAX_PARAM_TEXT_LEN
            )
            event: dict[str, Any] = {
                "armed": kwargs.get("armed", True),
                "bypassed_count": kwargs.get("bypassed_count"),
                "credential_redaction": status,
                "direction": "tool_call",
                "event_type": kwargs.get("event_type", ""),
                "param_scan_degraded": bool(kwargs.get("param_scan_degraded", False)),
                "reason": safe,
                "rule_id": kwargs.get("rule_id"),
                "session_id": kwargs.get("session_id", ""),
                "severity": kwargs.get("severity"),
                "tier": kwargs.get("tier"),
                "tool": kwargs.get("tool", ""),
            }
            if kwargs.get("event_type") == "ingest_flagged":
                event["score"] = kwargs["score"]
            if kwargs.get("event_type") == "deferred":
                event["score"] = kwargs.get("score")
            if kwargs.get("event_type") == "deferred" and "deferred_to" in kwargs:
                event["deferred_to"] = kwargs["deferred_to"]
            sink = self._sink
            if sink is None:
                return False
            return bool(sink.emit(event))
        except Exception:
            return False

    def fallback_scanner(self) -> Scanner:
        """The syntactic scanner used before the pipeline exists."""
        with self._fallback_lock:
            if self._fallback is None:
                self._fallback = syntactic_scanner()
            return self._fallback

    def run(self, coro: Any, timeout: float | None = None) -> Any:
        """Run ``coro`` on the evaluation loop."""
        limit = self.limits.eval_timeout_s if timeout is None else timeout
        return self.runtime.run(coro, limit)

    def _budget(self) -> float:
        value = self.limits.init_wait_s
        if value <= 0:
            return 2.0
        return min(60.0, max(0.05, value))

    def _initialise(self) -> None:
        try:
            with self._init_lock:
                if self.phase is not Phase.STARTING or self._closed or self._building:
                    return
                self._building = True
            error: str | None = None
            if self.gate is not None:
                error = self.gate.wait()
            if self._closed:
                return
            if error:
                self.init_error = error or "initialization failed"
                self.phase = Phase.FAILED
                logger.error("Petasos initialization failed: %s", self.init_error)
                return
            snap = self._pending if self._pending is not None else self._read()
            if snap is not None:
                self._secret_invalid = snap.secret_invalid
            config, secrets = self._materialise(snap)
            if snap is not None and snap.error is None:
                self._token = snap.token
                self.armed = snap.armed
            engine = build_engine(
                config,
                secrets,
                host=self.host,
                scanners=self.scanners,
                registry=self.registry,
                logger=logger,
                secret_invalid=self._secret_invalid,
                origin=snap.origin if snap is not None and snap.error is None else None,
                check_failures=self.check_failures,
            )
            self._install_secret(secrets)
            self.engine = engine
            self.fail_mode = engine.fail_mode()
            self.phase = Phase.READY
        except Exception as exc:
            self.init_error = str(exc) or type(exc).__name__
            self.phase = Phase.FAILED
            logger.error("Petasos initialization failed: %s", exc, exc_info=True)
        finally:
            self._init_done.set()

    def _observe(self, *, announce: bool) -> None:
        if self._closed:
            return
        snap = self._read()
        if snap is None:
            return
        self.armed = snap.armed
        if snap.error or snap.config is None:
            self.book.log_reload_failure(snap.error or "build failed")
            return
        self.fail_mode = snap.config.fail_mode
        self._pending = snap
        if not announce:
            return
        engine = self.engine
        if engine is None or self.phase is not Phase.READY:
            return
        if snap.token == self._token:
            return
        try:
            before = engine.config
            apply_snapshot(engine, snap.config, snap.secrets, logger, origin=snap.origin)
            record_applied_settings(self, before)
        except Exception as exc:
            self.book.log_reload_failure(f"apply failed: {exc}")
            return
        self._token = snap.token
        self.fail_mode = engine.fail_mode()
        self._install_secret(engine.secrets)
        if announce:
            self.book.log_reconfigured()

    def _read(self) -> SettingsSnapshot | None:
        try:
            snap = self.source()
        except Exception as exc:
            self.book.log_reload_failure(f"build failed: {exc}")
            return None
        if not isinstance(snap, SettingsSnapshot):
            self.book.log_reload_failure(
                "build failed: settings source returned an unexpected value"
            )
            return None
        return snap

    def _materialise(self, snap: SettingsSnapshot | None) -> tuple[PetasosConfig, Any]:
        from petasos.config.secrets import Secrets

        if snap is None or snap.error or snap.config is None:
            detail = None if snap is None or snap.error is None else snap.error
            if detail:
                logger.error("PetasosConfig validation failed: %s — using defaults", detail)
            return PetasosConfig(), Secrets()
        return snap.config, snap.secrets

    def _install_secret(self, secrets: Any) -> None:
        secret = getattr(secrets, "session_secret", None)
        if self._spool is not None:
            try:
                self._spool.set_secret(secret if isinstance(secret, bytes) else None)
            except Exception as exc:
                logger.warning(
                    "PETASOS_INTEGRITY spool-key install failed: %s — integrity off", exc
                )
