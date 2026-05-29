from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from types import MappingProxyType
from typing import Any

from petasos._types import Direction, ScanFinding, ScanResult, Severity

_logger = logging.getLogger(__name__)

_COMPONENT_TAXONOMY: MappingProxyType[str, tuple[str, str, Severity]] = MappingProxyType(
    {
        "prompt_guard": (
            "petasos.llamafirewall.prompt-guard",
            "injection",
            Severity.HIGH,
        ),
        "alignment_check": (
            "petasos.llamafirewall.alignment-check",
            "alignment",
            Severity.HIGH,
        ),
        "code_shield": (
            "petasos.llamafirewall.code-shield",
            "unsafe_code",
            Severity.MEDIUM,
        ),
    }
)


class LlamaFirewallScanner:
    def __init__(
        self,
        *,
        enable_prompt_guard: bool = True,
        enable_alignment_check: bool = False,
        enable_code_shield: bool = False,
    ) -> None:
        self._enable_prompt_guard = enable_prompt_guard
        self._enable_alignment_check = enable_alignment_check
        self._enable_code_shield = enable_code_shield
        self._loaded = False
        self._load_error: str | None = None
        self._lock = threading.Lock()
        self._components: dict[str, Any] = {}
        self._user_message_cls: type[Any] | None = None
        self._assistant_message_cls: type[Any] | None = None
        self._allow_decision: Any = None

    @property
    def name(self) -> str:
        return "llama_firewall"

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._load_error is None
        with self._lock:
            if self._loaded:
                return self._load_error is None
            self._loaded = True
            try:
                from llamafirewall import (
                    AssistantMessage,
                    LlamaFirewall,
                    Role,
                    ScanDecision,
                    ScannerType,
                    UserMessage,
                )

                self._user_message_cls = UserMessage
                self._assistant_message_cls = AssistantMessage
                self._allow_decision = ScanDecision.ALLOW

                _COMPONENT_MAP: dict[str, Any] = {
                    "prompt_guard": ScannerType.PROMPT_GUARD,
                    "alignment_check": ScannerType.AGENT_ALIGNMENT,
                    "code_shield": ScannerType.CODE_SHIELD,
                }
                _ENABLED: dict[str, bool] = {
                    "prompt_guard": self._enable_prompt_guard,
                    "alignment_check": self._enable_alignment_check,
                    "code_shield": self._enable_code_shield,
                }
                for comp_name, scanner_type in _COMPONENT_MAP.items():
                    if _ENABLED[comp_name]:
                        self._components[comp_name] = LlamaFirewall(
                            scanners={
                                Role.USER: [scanner_type],
                                Role.ASSISTANT: [scanner_type],
                            }
                        )
                if not self._components:
                    _logger.warning(
                        "LlamaFirewallScanner: all components disabled — "
                        "scan() will return error, not clean"
                    )
                return True
            except ImportError:
                self._components.clear()
                self._load_error = (
                    "llamafirewall not installed. pip install petasos[llamafirewall]"
                )
                return False
            except Exception as exc:
                self._components.clear()
                self._load_error = f"llamafirewall init failed: {exc}"
                return False

    def _scan_sync(self, text: str, direction: Direction) -> tuple[list[ScanFinding], list[str]]:
        if self._user_message_cls is None or self._assistant_message_cls is None:
            return [], ["internal error: message type classes not initialized"]

        if direction == "inbound":
            message = self._user_message_cls(content=text)
        else:
            message = self._assistant_message_cls(content=text)

        findings: list[ScanFinding] = []
        errors: list[str] = []

        for comp_name, fw_instance in self._components.items():
            try:
                result = fw_instance.scan(message)
                if result.decision != self._allow_decision:
                    rule_id, finding_type, severity = _COMPONENT_TAXONOMY[comp_name]
                    raw_score = result.score if result.score is not None else 1.0
                    confidence = (
                        0.0 if not math.isfinite(raw_score) else max(0.0, min(1.0, raw_score))
                    )
                    findings.append(
                        ScanFinding(
                            rule_id=rule_id,
                            finding_type=finding_type,
                            severity=severity,
                            confidence=confidence,
                            message=result.reason
                            or (f"{comp_name} flagged content ({result.decision.name})"),
                            scanner_name=self.name,
                            position=None,
                            matched_text=None,
                        )
                    )
            except Exception as exc:
                errors.append(f"{comp_name}: {exc}")

        return findings, errors

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
            if not self._ensure_loaded():
                elapsed = (time.perf_counter() - start) * 1000
                return ScanResult(
                    scanner_name=self.name,
                    findings=(),
                    duration_ms=elapsed,
                    error=self._load_error,
                )

            if not self._components:
                elapsed = (time.perf_counter() - start) * 1000
                return ScanResult(
                    scanner_name=self.name,
                    findings=(),
                    duration_ms=elapsed,
                    error="all components disabled — no ML inspection performed",
                )

            findings, errors = await asyncio.to_thread(self._scan_sync, text, direction)
            elapsed = (time.perf_counter() - start) * 1000
            error_str = "; ".join(errors) if errors else None
            return ScanResult(
                scanner_name=self.name,
                findings=tuple(findings),
                duration_ms=elapsed,
                error=error_str,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return ScanResult(
                scanner_name=self.name,
                findings=(),
                duration_ms=elapsed,
                error=str(exc),
            )
