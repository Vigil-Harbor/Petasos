from __future__ import annotations

import asyncio
import importlib.util
import logging
import math
import sys
import threading
import time
from typing import Any

from petasos._types import Direction, ScanFinding, ScanResult, Severity

_REQUIRED_PACKAGES: tuple[str, ...] = ("llm_guard",)

_INSTALL_HINT = "llm_guard not installed. pip install petasos[llm-guard]"

_logger = logging.getLogger(__name__)

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
        self._lock: threading.Lock = threading.Lock()
        self._scanners: list[tuple[str, str, Severity, Any]] = []

    @property
    def name(self) -> str:
        return "llm_guard"

    def availability(self) -> tuple[bool, str | None]:
        """Cheap backend-presence probe. Never imports the backend."""
        if self._load_error is not None and not self._load_error_retryable:
            return (False, self._load_error)
        for pkg in (*_REQUIRED_PACKAGES, "llm_guard.input_scanners"):
            if pkg in sys.modules and sys.modules[pkg] is not None:
                continue
            try:
                spec = importlib.util.find_spec(pkg)
            except Exception:
                return (False, _INSTALL_HINT)
            if spec is None or spec.origin is None:
                return (False, _INSTALL_HINT)
        return (True, None)

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
                    avail, _reason = self.availability()
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
                if module_absent:
                    _logger.debug("llm-guard logging shield skipped: %s", exc)
                else:
                    _logger.warning(
                        "llm-guard logging shield failed (%s: %s); scans may "
                        "fail with weakref errors under wrapped stdio",
                        type(exc).__name__,
                        exc,
                    )

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

            self._loaded = True
        except Exception as exc:
            from petasos.scanners import _is_missing_package

            if isinstance(exc, ImportError) and _is_missing_package(exc, set(_REQUIRED_PACKAGES)):
                self._load_error = _INSTALL_HINT
                self._load_error_retryable = True
            else:
                avail, avail_reason = self.availability()
                if avail:
                    self._load_error = str(exc)
                    self._load_error_retryable = False
                else:
                    self._load_error = avail_reason or str(exc)
                    self._load_error_retryable = True

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
        findings: list[ScanFinding] = []
        errors: list[str] = []
        for rule_id, finding_type, severity, sub_scanner in self._scanners:
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
