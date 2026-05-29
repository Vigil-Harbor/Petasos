from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import Any

from petasos._types import Direction, ScanFinding, ScanResult, Severity


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
        self._lock: threading.Lock = threading.Lock()
        self._scanners: list[tuple[str, str, Severity, Any]] = []

    @property
    def name(self) -> str:
        return "llm_guard"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._load_error is not None:
            return
        with self._lock:
            if self._loaded:
                return
            if self._load_error is not None:
                return
            try:
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
                self._load_error = str(exc)

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
