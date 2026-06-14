from __future__ import annotations

import asyncio
import importlib.util
import logging
import math
import sys
import threading
import time
from typing import Any

from petasos._types import (
    AVAILABILITY_CAUSE_ABSENT,
    AVAILABILITY_CAUSE_LOAD_FAILED,
    AvailabilityCause,
    Direction,
    ScanFinding,
    ScanResult,
    Severity,
)

_REQUIRED_PACKAGES: tuple[str, ...] = ("llm_guard",)

# D9 (PET-108): hard per-process cap on weakref-shaped load attempts. One initial
# attempt + two retries. Never reset by success — only reset() clears the counter.
_MAX_LOAD_ATTEMPTS = 3

_INSTALL_HINT = "llm_guard not installed. pip install petasos[llm-guard]"

_logger = logging.getLogger(__name__)


def _is_weakref_shaped(exc: BaseException) -> bool:
    """True when ``exc`` is the stdio-weakref load failure carved out by PET-108.

    The live signature is ``cannot create weak reference to '_SafeWriter'
    object`` — a TypeError whose message mentions a weak reference. This failure
    class is stdio-state-transient (the host can rebind a weakref-able stdout),
    so it is reclassified retryable; everything else stays fail-once (D1/D4).
    """
    return isinstance(exc, TypeError) and "weak reference" in str(exc).lower()


# Serializes the logging-shield's stdio snapshot/restore window across scanner
# instances: self._lock is per-instance, but sys.stdout/sys.stderr are
# process-global — unserialized, two concurrent loads could interleave their
# windows and strand colorama's wrapper as the final global (PET-92, D9).
_SHIELD_LOCK = threading.Lock()


class _WeakrefableStdout:
    """Weakref-able passthrough to the *current* ``sys.stdout``.

    structlog's PrintLogger registers its output stream as a weak key in a
    module-level lock registry (``structlog._output.WRITE_LOCKS``). Host
    processes (Hermes) install slots-only stdio wrappers that do not support
    weak references, so handing structlog the raw ``sys.stdout`` crashes every
    log emission. This proxy supports weak references and delegates each call
    to whatever ``sys.stdout`` is at call time — output still flows through the
    host's crash-resistant wrapper, and the proxy keeps working if the host
    rebinds stdio after init. A ``None`` stdout (pythonw / detached console)
    swallows writes; a self-referential rebinding (``sys.stdout`` set to this
    proxy) short-circuits instead of recursing.
    """

    def write(self, s: str) -> int:
        stream = sys.stdout
        if stream is None or stream is self:
            return len(s)
        return stream.write(s) or len(s)

    def flush(self) -> None:
        stream = sys.stdout
        if stream is not None and stream is not self:
            stream.flush()

    def isatty(self) -> bool:
        stream = sys.stdout
        try:
            return stream is not None and stream is not self and bool(stream.isatty())
        except Exception:
            return False


_STDOUT_PROXY = _WeakrefableStdout()


class LlmGuardScanner:
    def __init__(
        self,
        *,
        threshold: float = 0.85,
        enable_toxicity: bool = False,
        enable_secrets: bool = False,
        enable_invisible_text: bool = True,
        enable_ban_topics: bool = False,
        ban_topics: list[str] | None = None,
    ) -> None:
        if enable_ban_topics and not ban_topics:
            raise ValueError("ban_topics must be a non-empty list when enable_ban_topics=True")
        self._threshold = threshold
        self._enable_toxicity = enable_toxicity
        self._enable_secrets = enable_secrets
        self._enable_invisible_text = enable_invisible_text
        self._enable_ban_topics = enable_ban_topics
        self._ban_topics = ban_topics

        self._loaded: bool = False
        self._load_error: str | None = None
        self._load_error_retryable: bool = False
        self._load_attempts: int = 0  # D2: weakref-shaped attempts (hard per-process cap)
        self._load_health_error: str | None = None  # D6: health backing; success-only clear
        self._lock: threading.Lock = threading.Lock()
        self._scanners: list[tuple[str, str, Severity, Any]] = []

    @property
    def name(self) -> str:
        return "llm_guard"

    def availability(self) -> tuple[bool, str | None, AvailabilityCause | None]:
        """Cheap backend-presence probe. Never imports the backend.

        Returns ``(ok, reason, cause)`` (PET-103). A terminal (non-retryable)
        ``_load_error`` is a genuine load crash — the missing-package case is
        caught earlier by the ``find_spec`` probe and the load path marks it
        retryable, so it never reaches this branch — hence ``load_failed``.
        ``find_spec`` misses are ``absent``.
        """
        if self._load_error is not None and not self._load_error_retryable:
            return (False, self._load_error, AVAILABILITY_CAUSE_LOAD_FAILED)
        for pkg in (*_REQUIRED_PACKAGES, "llm_guard.input_scanners"):
            if pkg in sys.modules and sys.modules[pkg] is not None:
                continue
            try:
                spec = importlib.util.find_spec(pkg)
            except Exception:
                return (False, _INSTALL_HINT, AVAILABILITY_CAUSE_ABSENT)
            if spec is None or spec.origin is None:
                return (False, _INSTALL_HINT, AVAILABILITY_CAUSE_ABSENT)
        return (True, None, None)

    def load_health(self) -> tuple[bool, str | None]:
        """Return ``(failed, last_error)`` for the console dashboard (PET-108).

        Lock-free (mirrors ``availability()``): ``_load_health_error`` is cleared
        only on a confirmed load success and in ``reset()`` — never at the
        retry-clear site — so a reader sees only a failed state (retryable,
        pending, or terminal) or a post-success not-failed state, never a torn
        intermediate (D6). The clear is sequenced before ``_loaded`` is published
        on the success path so a composite health read cannot report a stale
        ``degraded`` after the load already succeeded.
        """
        err = self._load_health_error
        return (err is not None, err)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._load_error is not None:
            if not self._load_error_retryable:
                return
            with self._lock:
                if self._loaded:
                    return
                if self._load_error is not None and not self._load_error_retryable:
                    return
                if self._load_error is not None and self._load_error_retryable:
                    avail, _reason, _cause = self.availability()
                    if not avail:
                        return
                    self._load_error = None
                    self._load_error_retryable = False
                    self._loaded = False
                    self._scanners = []
                self._do_load()
            return
        with self._lock:
            if self._loaded:
                return
            if self._load_error is not None:
                return
            self._do_load()

    def _do_load(self) -> None:
        try:
            # PET-92 logging shield: configure llm-guard's structlog output to
            # the weakref-able proxy before importing/instantiating scanners.
            # structlog's default factory captures sys.stdout at import time;
            # under a slots-only host wrapper (_SafeWriter) the first emitted
            # log dies on a weakref. Failures here must never block the load —
            # they degrade to a log line and the import below stays
            # authoritative for _load_error classification.
            try:
                from llm_guard.util import configure_logger

                # configure_logger constructs structlog.dev.ConsoleRenderer,
                # which lets colorama globally swap sys.stdout/sys.stderr on
                # Windows — snapshot and restore so the host's stdio wrappers
                # keep their identity (D9). _SHIELD_LOCK serializes the window
                # across instances; stdio is process-global.
                with _SHIELD_LOCK:
                    saved_out, saved_err = sys.stdout, sys.stderr
                    try:
                        configure_logger(stream=_STDOUT_PROXY)
                    finally:
                        sys.stdout, sys.stderr = saved_out, saved_err
            except Exception as exc:
                # Suppress the breadcrumb only for true module absence (base
                # install / blocked import) — the input_scanners import below
                # sets the authoritative _load_error one statement later. A
                # "cannot import name" ImportError from an importable
                # llm_guard.util IS the API-drift tripwire and must warn.
                module_absent = isinstance(exc, ModuleNotFoundError) or (
                    isinstance(exc, ImportError)
                    and any(
                        sys.modules.get(name, True) is None
                        for name in ("llm_guard", "llm_guard.util")
                    )
                )
                try:
                    if module_absent:
                        _logger.debug("llm-guard logging shield skipped: %s", exc)
                    else:
                        _logger.warning(
                            "llm-guard logging shield failed (%s: %s); scans may "
                            "fail with weakref errors under wrapped stdio",
                            type(exc).__name__,
                            exc,
                        )
                except Exception:
                    pass

            from llm_guard.input_scanners import (
                InvisibleText,
                PromptInjection,
            )

            self._scanners = []

            self._scanners.append(
                (
                    "petasos.llmguard.injection",
                    "injection",
                    Severity.HIGH,
                    PromptInjection(threshold=self._threshold),
                )
            )

            if self._enable_invisible_text:
                self._scanners.append(
                    (
                        "petasos.llmguard.invisible-text",
                        "encoding",
                        Severity.MEDIUM,
                        InvisibleText(),
                    )
                )

            if self._enable_toxicity:
                from llm_guard.input_scanners import Toxicity

                self._scanners.append(
                    (
                        "petasos.llmguard.toxicity",
                        "toxicity",
                        Severity.MEDIUM,
                        Toxicity(),
                    )
                )

            if self._enable_ban_topics:
                from llm_guard.input_scanners import BanTopics

                self._scanners.append(
                    (
                        "petasos.llmguard.ban-topics",
                        "policy",
                        Severity.MEDIUM,
                        BanTopics(topics=self._ban_topics),
                    )
                )

            if self._enable_secrets:
                from llm_guard.input_scanners import Secrets

                self._scanners.append(
                    (
                        "petasos.llmguard.secrets",
                        "credential",
                        Severity.HIGH,
                        Secrets(),
                    )
                )

            self._load_health_error = None  # D6: success-only clear, sequenced BEFORE
            self._loaded = True  # ........... publishing success (avoids a stale degraded read)
        except Exception as exc:
            from petasos.scanners import _is_missing_package

            if isinstance(exc, ImportError) and _is_missing_package(exc, set(_REQUIRED_PACKAGES)):
                self._load_error = _INSTALL_HINT
                self._load_error_retryable = True
            else:
                avail, avail_reason, _cause = self.availability()
                if avail:
                    self._load_error = str(exc)
                    if _is_weakref_shaped(exc):  # D1: stdio-weakref carve-out
                        self._load_attempts += 1  # D2: count weakref attempts only
                        self._load_error_retryable = self._load_attempts < _MAX_LOAD_ATTEMPTS
                    else:
                        self._load_error_retryable = False  # D4: non-weakref stays fail-once
                else:
                    self._load_error = avail_reason or str(exc)
                    self._load_error_retryable = True
            self._load_health_error = self._load_error  # D6: set on every failure path

    def reset(self) -> None:
        """Clear cached load error to allow re-attempt (e.g., after pip install).

        Caller must ensure no scan() calls are in flight when calling reset().
        Calling reset() during active scanning may produce silent false-negatives
        (empty findings with no error) because _scanners is cleared while
        _scan_sync may still be iterating. This is the caller's responsibility --
        reset() is for maintenance windows (post-install), not runtime use.
        """
        with self._lock:
            self._load_error = None
            self._load_error_retryable = False
            self._loaded = False
            self._scanners = []
            self._load_health_error = None  # D6: cleared only here and on confirmed success
            self._load_attempts = 0  # D2: the only place the weakref cap counter resets

    async def scan(
        self,
        text: str,
        *,
        direction: Direction = "inbound",
        session_id: str | None = None,
    ) -> ScanResult:
        """Scan ``text`` and return a ScanResult (never raises).

        Cancellation residual (SCAN-03): inference runs in a worker thread via
        ``asyncio.to_thread``. Cancelling the awaiting task frees the event loop
        promptly, but the worker thread runs to completion on the default
        executor — cancellation does not interrupt in-flight ML inference. A
        cancellable-executor path is future work.
        """
        start = time.perf_counter()
        try:
            self._ensure_loaded()
            if self._load_error is not None:
                elapsed = (time.perf_counter() - start) * 1000
                return ScanResult(
                    scanner_name="llm_guard",
                    findings=(),
                    duration_ms=elapsed,
                    error=self._load_error,
                )
            findings, errors = await asyncio.to_thread(self._scan_sync, text)
            elapsed = (time.perf_counter() - start) * 1000
            return ScanResult(
                scanner_name="llm_guard",
                findings=tuple(findings),
                duration_ms=elapsed,
                error="; ".join(errors) if errors else None,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return ScanResult(
                scanner_name="llm_guard",
                findings=(),
                duration_ms=elapsed,
                error=str(exc),
            )

    def _scan_sync(self, text: str) -> tuple[list[ScanFinding], list[str]]:
        # D8 (PET-108): bind self._scanners to a local once at entry, then guard
        # on empty. Every clear site (_do_load, _ensure_loaded's retry-clear,
        # reset()) *rebinds* self._scanners = [] (never mutates in place), so this
        # local is a safe read-once alias — not a copy. If any clear site is ever
        # changed to in-place mutation (.clear() / del [:]), this MUST become
        # `scanners = list(self._scanners)` or a concurrent mutation tears the loop.
        scanners = self._scanners
        if not scanners:
            # A concurrent clear (reset()/retry) emptied _scanners after scan()'s
            # pre-checks passed (loaded, _load_error is None). Return an explicit
            # error so fail-mode 'degraded' blocks, instead of the silent
            # false-negative (findings=(), error=None) an unguarded loop would
            # yield. A successfully-loaded llm_guard always has >=1 scanner (the
            # injection scanner is unconditional), so this is never the normal path.
            return [], ["llm_guard: scanners cleared mid-scan (load reset in flight)"]
        findings: list[ScanFinding] = []
        errors: list[str] = []
        for rule_id, finding_type, severity, sub_scanner in scanners:
            try:
                _sanitized, is_valid, risk_score = sub_scanner.scan(text)
                if not is_valid:
                    _clamped = (
                        0.0 if not math.isfinite(risk_score) else max(0.0, min(1.0, risk_score))
                    )
                    findings.append(
                        ScanFinding(
                            rule_id=rule_id,
                            finding_type=finding_type,
                            severity=severity,
                            confidence=_clamped,
                            message=f"LLM Guard {finding_type} detection triggered",
                            scanner_name="llm_guard",
                            position=None,
                            matched_text=None,
                        )
                    )
            except Exception as exc:
                errors.append(f"{rule_id}: {exc}")
        return findings, errors
